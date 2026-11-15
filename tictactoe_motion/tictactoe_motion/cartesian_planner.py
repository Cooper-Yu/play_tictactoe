"""Plan bounded fixed-height tool paths through the existing MoveIt services."""

import copy
import math
import time

from geometry_msgs.msg import Pose
from moveit_msgs.srv import GetCartesianPath, GetPositionFK
from rclpy.clock import Clock, ClockType
from rclpy.time import Time


def xyz(pose):
    return (pose.position.x, pose.position.y, pose.position.z)


def orientation_error(a, b):
    qa = (a.x, a.y, a.z, a.w)
    qb = (b.x, b.y, b.z, b.w)
    norms = math.sqrt(sum(x*x for x in qa) * sum(x*x for x in qb))
    if not math.isfinite(norms) or norms < 1e-12:
        raise ValueError('Invalid quaternion')
    return 2 * math.acos(min(1.0, abs(sum(x*y for x, y in zip(qa, qb))) / norms))


def polyline_error(point, poses):
    """! @brief Measure distance to the requested piecewise straight path in meters."""
    distances = []
    for a, b in zip(poses, poses[1:]):
        start, end = xyz(a), xyz(b)
        vector = [y-x for x, y in zip(start, end)]
        length2 = sum(x*x for x in vector)
        t = min(1.0, max(0.0, sum((p-x)*v for p, x, v in zip(point, start, vector)) / length2)) if length2 else 0.0
        distances.append(math.dist(point, [x+t*v for x, v in zip(start, vector)]))
    return min(distances)


def stretch_timing(trajectory, velocity, acceleration, minimum_duration):
    """! @brief Slow a timed MoveIt trajectory without increasing native derivatives."""
    if not all(math.isfinite(v) and 0 < v <= 1 for v in (velocity, acceleration)):
        raise ValueError('Velocity and acceleration scaling must be in (0, 1]')
    points = trajectory.joint_trajectory.points
    times = [p.time_from_start.sec + p.time_from_start.nanosec * 1e-9 for p in points]
    if len(times) < 2 or times[0] != 0 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Cartesian trajectory must have strictly increasing timing from zero')
    factor = max(1.0 / velocity, 1.0 / math.sqrt(acceleration), minimum_duration / times[-1], 1.0)
    result = copy.deepcopy(trajectory)
    for point, stamp in zip(result.joint_trajectory.points, times):
        nanoseconds = round(stamp * factor * 1e9)
        point.time_from_start.sec, point.time_from_start.nanosec = divmod(nanoseconds, 10**9)
        point.velocities = [v/factor for v in point.velocities]
        point.accelerations = [a/factor**2 for a in point.accelerations]
    return result


def interpolate_joint_segment(a, b, fraction):
    """! @brief Sample the controller's linear/cubic/quintic interpolation from derivatives."""
    dt = (b.time_from_start.sec-a.time_from_start.sec) + (b.time_from_start.nanosec-a.time_from_start.nanosec)*1e-9
    if dt <= 0:
        raise ValueError('Non-increasing segment timing')
    count = len(a.positions)
    if any(len(v) not in (0, count) for v in (a.velocities, b.velocities, a.accelerations, b.accelerations)):
        raise ValueError('Invalid derivative dimensions')
    values = []
    for i, (q0, q1) in enumerate(zip(a.positions, b.positions)):
        s = fraction
        if not a.velocities or not b.velocities:
            values.append(q0+(q1-q0)*s)
            continue
        v0, v1 = a.velocities[i]*dt, b.velocities[i]*dt
        if not a.accelerations or not b.accelerations:
            values.append((2*s**3-3*s**2+1)*q0+(s**3-2*s**2+s)*v0+(-2*s**3+3*s**2)*q1+(s**3-s**2)*v1)
            continue
        a0, a1 = a.accelerations[i]*dt**2, b.accelerations[i]*dt**2
        d0, d1, d2 = q1-q0-v0-a0/2, v1-v0-a0, a1-a0
        c3, c4, c5 = 10*d0-4*d1+d2/2, -15*d0+7*d1-d2, 6*d0-3*d1+d2/2
        values.append(q0+v0*s+a0*s*s/2+c3*s**3+c4*s**4+c5*s**5)
    return values

class CartesianPlanner:
    """! @brief Plan only; reject partial, discontinuous or geometrically distorted paths.

    Preserve base_link Z and link6 orientation. Validate returned joint samples and
    their midpoints with FK before exposing a trajectory to the existing executor.
    A stopped or superseded service response can never restore an executable plan.
    """

    def __init__(self, node):
        self.node = node
        self.settings = node.settings
        self.client = node.create_client(GetCartesianPath, self.settings['cartesian_service'])
        self.fk_client = node.create_client(GetPositionFK, '/compute_fk')
        self.future = None
        self.timer = None
        self.last_report = None

    def close(self):
        self.cancel()

    def cancel(self):
        if self.timer is not None:
            self.node.destroy_timer(self.timer)
            self.timer = None
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.future = None

    def start_pose(self):
        transform = self.node.get_current_pose()
        if transform is None:
            raise ValueError('link6 TF unavailable')
        stamp = Time.from_msg(transform.header.stamp)
        age = (self.node.get_clock().now() - stamp).nanoseconds * 1e-9
        if not -0.1 <= age <= self.settings['feedback_max_age']:
            raise ValueError('link6 TF is stale')
        pose = Pose()
        t = transform.transform.translation
        pose.position.x, pose.position.y, pose.position.z = t.x, t.y, t.z
        pose.orientation = copy.deepcopy(transform.transform.rotation)
        return pose

    def request_xy(self, dx, dy):
        try:
            if not all(math.isfinite(v) for v in (dx, dy)) or math.hypot(dx, dy) == 0:
                raise ValueError('dx/dy must be finite with nonzero displacement')
            start = self.start_pose()
            target = copy.deepcopy(start)
            target.position.x += dx
            target.position.y += dy
            return self.request_path([start, target])
        except (ValueError, TypeError) as error:
            self.node.get_logger().warning(str(error))
            if not self.node.is_planning and not self.node.trajectory_executor.is_executing:
                self.node.invalidate_plan()
            return False

    def request_path(self, poses):
        node = self.node
        if node.is_planning or node.is_recording or node.trajectory_executor.is_executing:
            node.get_logger().warning('Cannot plan Cartesian path while busy')
            return False
        node.invalidate_plan()
        self.last_report = None
        try:
            if not node.feedback_is_fresh():
                raise ValueError('Fresh joint feedback required')
            state = copy.deepcopy(node.current_joint_state)
            joints = dict(zip(state.name, state.position))
            if any(not math.isfinite(joints.get(f'joint{i}', math.nan)) for i in range(1, 7)):
                raise ValueError('Complete finite arm joints required')
            if not 2 <= len(poses) <= 500:
                raise ValueError('Path must contain 2..500 poses')
            start = self.start_pose()
            if math.dist(xyz(start), xyz(poses[0])) > 0.0001:
                raise ValueError('Path start no longer matches current pose')
            for pose in poses:
                if not all(math.isfinite(v) for v in xyz(pose)):
                    raise ValueError('Path position must be finite')
                if abs(pose.position.z-start.position.z) > 1e-9 or orientation_error(pose.orientation, start.orientation) > 1e-6:
                    raise ValueError('This planner requires fixed Z and orientation')
            length = sum(math.dist(xyz(a), xyz(b)) for a, b in zip(poses, poses[1:]))
            if not 0 < length <= self.settings['cartesian_max_length']:
                raise ValueError('Path length exceeds configured range')
            self.velocity = node.get_parameter('velocity_scaling').value
            self.acceleration = node.get_parameter('acceleration_scaling').value
            if not all(math.isfinite(v) and 0 < v <= 1 for v in (self.velocity, self.acceleration)):
                raise ValueError('Velocity and acceleration scaling must be in (0, 1]')
            if not self.client.service_is_ready() or not self.fk_client.service_is_ready():
                raise ValueError('Cartesian or FK service unavailable')
            request = GetCartesianPath.Request()
            request.header.frame_id = 'base_link'
            request.start_state.joint_state = state
            request.start_state.is_diff = True
            request.group_name = self.settings['planning_group']
            request.link_name = 'link6'
            request.waypoints = copy.deepcopy(poses[1:])
            request.max_step = self.settings['cartesian_step']
            request.jump_threshold = 0.0  # Absolute returned-joint guard below is authoritative.
            request.avoid_collisions = True
            self.poses, self.state, self.length = copy.deepcopy(poses), state, length
            self.generation = node.plan_generation
            node.is_planning = True
            self.deadline = time.monotonic() + self.settings['cartesian_timeout']
            self.timer = node.create_timer(0.1, self.check_timeout, clock=Clock(clock_type=ClockType.STEADY_TIME))
            self.future = self.client.call_async(request)
            generation = self.generation
            self.future.add_done_callback(lambda f: self.path_ready(f, generation))
            return True
        except Exception as error:
            self.fail(str(error))
            return False

    def active(self, generation):
        return generation == self.node.plan_generation and self.node.is_planning

    def check_timeout(self):
        if time.monotonic() >= self.deadline:
            self.fail('Cartesian planning/FK validation timed out')

    def fail(self, message):
        self.node.get_logger().warning('Cartesian plan rejected: ' + message)
        self.node.is_planning = False
        self.node.invalidate_plan()
        self.cancel()
        self.last_report = {'accepted': False, 'reason': message}

    def path_ready(self, future, generation):
        if not self.active(generation):
            return
        try:
            response = future.result()
            if response.error_code.val != 1 or not math.isfinite(response.fraction) or response.fraction < 1.0-1e-9:
                raise ValueError(f'Incomplete Cartesian path: fraction={response.fraction}, error={response.error_code.val}')
            trajectory = response.solution
            jt = trajectory.joint_trajectory
            if set(jt.joint_names) != {f'joint{i}' for i in range(1, 7)} or not 2 <= len(jt.points) <= 1000:
                raise ValueError('Invalid Cartesian joint trajectory')
            previous = None
            self.checks = []
            first = dict(zip(self.state.name, self.state.position))
            for point in jt.points:
                row = list(point.positions)
                if len(row) != 6 or not all(math.isfinite(v) for v in row + list(point.velocities) + list(point.accelerations)):
                    raise ValueError('Incomplete/nonfinite trajectory point')
                if previous is None:
                    if any(abs(v-first[n]) > self.settings['execution_start_tolerance'] for n, v in zip(jt.joint_names, row)):
                        raise ValueError('Cartesian start differs from captured joints')
                else:
                    if max(abs(a-b) for a, b in zip(row, previous.positions)) > self.settings['cartesian_joint_jump']:
                        raise ValueError('Cartesian joint jump exceeds limit')
                    for fraction in (.25, .5, .75):
                        self.checks.append(interpolate_joint_segment(previous, point, fraction))
                self.checks.append(row)
                previous = point
            self.candidate = stretch_timing(trajectory, self.velocity, self.acceleration,
                                            self.length/self.settings['cartesian_speed'])
            self.index, self.max_error, self.max_angle = 0, 0.0, 0.0
            self.fk_poses = []
            self.request_fk(generation)
        except Exception as error:
            self.fail(str(error))

    def request_fk(self, generation):
        request = GetPositionFK.Request()
        request.header.frame_id = 'base_link'
        request.fk_link_names = ['link6']
        request.robot_state.joint_state = copy.deepcopy(self.state)
        values = dict(zip(self.candidate.joint_trajectory.joint_names, self.checks[self.index]))
        request.robot_state.joint_state.position = [values.get(n, v) for n, v in zip(self.state.name, self.state.position)]
        request.robot_state.is_diff = True
        self.future = self.fk_client.call_async(request)
        self.future.add_done_callback(lambda f: self.fk_ready(f, generation))

    def fk_ready(self, future, generation):
        if not self.active(generation):
            return
        try:
            result = future.result()
            if result.error_code.val != 1 or not result.pose_stamped:
                raise ValueError('FK validation failed')
            pose = result.pose_stamped[0].pose
            self.fk_poses.append(copy.deepcopy(pose))
            distance = polyline_error(xyz(pose), self.poses)
            angle = orientation_error(pose.orientation, self.poses[0].orientation)
            if not math.isfinite(distance) or distance > self.settings['cartesian_path_tolerance'] or angle > self.settings['cartesian_orientation_tolerance']:
                raise ValueError(f'FK path deviation: {distance:.6f} m, {angle:.6f} rad')
            self.max_error, self.max_angle = max(self.max_error, distance), max(self.max_angle, angle)
            self.index += 1
            if self.index < len(self.checks):
                self.request_fk(generation)
                return
            if math.dist(xyz(pose), xyz(self.poses[-1])) > self.settings['return_position_tolerance']:
                raise ValueError('Cartesian endpoint error exceeds tolerance')
            coverage_error = max(polyline_error(xyz(p), self.fk_poses) for p in self.poses)
            if coverage_error > self.settings['cartesian_path_tolerance']:
                raise ValueError(f'FK path coverage gap: {coverage_error:.6f} m')
            self.node.planned_trajectory = self.candidate
            self.node.planned_target_pose = copy.deepcopy(self.poses[-1])
            self.node.is_planning = False
            self.last_report = {'accepted': True, 'fk_samples': self.index,
                                'max_path_error_m': self.max_error, 'max_orientation_error_rad': self.max_angle,
                                'path_length_m': self.length, 'max_uncovered_waypoint_m': coverage_error}
            self.cancel()
            self.node.get_logger().info('Complete Cartesian trajectory validated; explicit execution required')
        except Exception as error:
            self.fail(str(error))
