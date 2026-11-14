from rclpy.node import Node
from sensor_msgs.msg import JointState
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from tf2_ros import TransformException
from geometry_msgs.msg import Pose
import rclpy
from moveit_msgs.action import MoveGroup, ExecuteTrajectory
from shape_msgs.msg import SolidPrimitive
from moveit_msgs.msg import PositionConstraint, OrientationConstraint, Constraints
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus
from moveit_msgs.msg import MoveItErrorCodes
import math
from std_srvs.srv import Trigger
import time


class MotionPlanner(Node):
    def __init__(self):
        super().__init__("motion_planner")
        self.current_joint_state = None
        self.planned_trajectory = None
        self.planned_target_pose = None
        self.execution_start_transform = None
        self.joint_state_subscription = self.create_subscription(
            JointState, "/joint_states", self.joint_state_callback, 10
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.state_timer = self.create_timer(1.0, self.report_current_state)

        self.move_client = ActionClient(self, MoveGroup, "/move_action")
        self.execute_client = ActionClient(
            self, ExecuteTrajectory, "/execute_trajectory"
        )
        self.execution_service = self.create_service(
            Trigger, "/execute_planned_trajectory", self.execution_trigger_callback
        )

        self.demo_timer = self.create_timer(3.0, self.run_planning_demo)

        self.declare_parameter("axis", "x")
        self.declare_parameter("distance", 0.0)
        self.declare_parameter("velocity_scaling", 0.1)
        self.declare_parameter("acceleration_scaling", 0.1)
        self.joint_state_sequence = 0

        self.settle_timer = None
        self.last_settle_sequence = 0
        self.previous_settle_positions = None
        self.stable_sample_count = 0

    def joint_state_callback(self, msg):
        self.current_joint_state = msg
        self.joint_state_sequence += 1

    def get_current_pose(self):
        try:
            transform = self.tf_buffer.lookup_transform("base_link", "link6", Time())
            return transform
        except TransformException as error:
            self.get_logger().warning(f"unable to obtain the pose of link6: {error}")
            return None

    def calculate_target_pose(self, current_transform, axis, distance):
        target_pose = Pose()
        translation = current_transform.transform.translation

        target_pose.position.x = translation.x
        target_pose.position.y = translation.y
        target_pose.position.z = translation.z

        rotation = current_transform.transform.rotation

        target_pose.orientation.x = rotation.x
        target_pose.orientation.y = rotation.y
        target_pose.orientation.z = rotation.z
        target_pose.orientation.w = rotation.w

        if axis == "x":
            target_pose.position.x = target_pose.position.x + distance
        elif axis == "y":
            target_pose.position.y = target_pose.position.y + distance
        elif axis == "z":
            target_pose.position.z = target_pose.position.z + distance
        else:
            raise ValueError("axis must be 'x', 'y', 'z'")
        return target_pose

    def report_current_state(self):
        if self.current_joint_state is None:
            self.get_logger().info("Waiting for joint states")
            return
        joint_position = dict(
            zip(self.current_joint_state.name, self.current_joint_state.position)
        )
        required_joints = [f"joint{i}" for i in range(1, 7)]
        if any(name not in joint_position for name in required_joints):
            self.get_logger().warning("Joint states are incomplete")
            return
        joint_summary = ", ".join(
            f"{name}={joint_position[name]:.4f}" for name in required_joints
        )
        self.get_logger().info(f"Joint positions (rad): {joint_summary}")
        transform = self.get_current_pose()
        if transform is None:
            return

        translation = transform.transform.translation
        orientation = transform.transform.rotation

        self.get_logger().info(
            f"link6 position (m): "
            f"x={translation.x:.4f}, "
            f"y={translation.y:.4f}, "
            f"z={translation.z:.4f}"
        )

        self.get_logger().info(
            f"link6 orientation (quaternion xyzw): "
            f"x={orientation.x:.4f}, "
            f"y={orientation.y:.4f}, "
            f"z={orientation.z:.4f}, "
            f"w={orientation.w:.4f}"
        )

    def build_planning_goal(self, target_pose, current_joint_state):
        goal = MoveGroup.Goal()

        velocity_scaling = self.get_parameter("velocity_scaling").value
        acceleration_scaling = self.get_parameter("acceleration_scaling").value
        if not 0.0 < velocity_scaling <= 1.0:
            self.get_logger().warning("velocity_scaling must be in (0, 1]")
            return None
        if not 0.0 < acceleration_scaling <= 1.0:
            self.get_logger().warning("acceleration_scaling must be in (0, 1]")
            return None

        goal.request.group_name = "arm"
        goal.request.allowed_planning_time = 5.0
        goal.request.max_velocity_scaling_factor = velocity_scaling
        goal.request.max_acceleration_scaling_factor = acceleration_scaling
        goal.request.num_planning_attempts = 1

        goal.request.start_state.joint_state = current_joint_state
        goal.request.start_state.is_diff = True

        position_constraint = PositionConstraint()
        position_constraint.header.frame_id = "base_link"
        position_constraint.link_name = "link6"
        position_constraint.weight = 1.0

        region = SolidPrimitive()
        region.type = SolidPrimitive.SPHERE
        region.dimensions = [0.0001]

        region_pose = Pose()
        region_pose.position = target_pose.position
        region_pose.orientation.w = 1.0

        position_constraint.constraint_region.primitives = [region]
        position_constraint.constraint_region.primitive_poses = [region_pose]

        orientation_constraint = OrientationConstraint()
        orientation_constraint.header.frame_id = "base_link"
        orientation_constraint.link_name = "link6"
        orientation_constraint.orientation = target_pose.orientation

        orientation_constraint.absolute_x_axis_tolerance = 0.01
        orientation_constraint.absolute_y_axis_tolerance = 0.01
        orientation_constraint.absolute_z_axis_tolerance = 0.01
        orientation_constraint.weight = 1.0

        target_constraints = Constraints()
        target_constraints.position_constraints = [position_constraint]
        target_constraints.orientation_constraints = [orientation_constraint]

        goal.request.goal_constraints = [target_constraints]

        goal.planning_options.plan_only = True
        return goal

    def request_plan(self, axis, distance):
        if self.current_joint_state is None:
            self.get_logger().warning("Cannot plan: joint states unavailable")
            return
        current_transform = self.get_current_pose()
        if current_transform is None:
            return
        target_pose = self.calculate_target_pose(current_transform, axis, distance)
        self.planned_target_pose = target_pose
        goal = self.build_planning_goal(target_pose, self.current_joint_state)
        if goal is None:
            return
        if not self.move_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().warning("MoveIt action server unavailable")
            return
        self.send_goal_future = self.move_client.send_goal_async(goal)
        self.send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warning("Planning goal rejected")
            return
        self.get_logger().info("Planning goal accepted")
        self.result_future = goal_handle.get_result_async()
        self.result_future.add_done_callback(self.planning_result_callback)

    def planning_result_callback(self, future):
        response = future.result()
        status = response.status
        result = response.result

        if (
            status == GoalStatus.STATUS_SUCCEEDED
            and result.error_code.val == MoveItErrorCodes.SUCCESS
        ):
            self.get_logger().info("Planning succeeded")
            self.planned_trajectory = result.planned_trajectory
            joint_trajectory = self.planned_trajectory.joint_trajectory

            if not joint_trajectory.points:
                self.get_logger().warning("Planned trajectory is empty")
                self.planned_trajectory = None
                return

            self.get_logger().info(
                f"Planned joints: {list(joint_trajectory.joint_names)}, "
                f"trajectory points: {len(joint_trajectory.points)}"
            )

            start_positions = joint_trajectory.points[0].positions
            end_positions = joint_trajectory.points[-1].positions

            for name, start, end in zip(
                joint_trajectory.joint_names, start_positions, end_positions
            ):
                self.get_logger().info(
                    f"{name}: start={start:.6f}, end={end:.6f}, "
                    f"delta={end - start:.6f} rad"
                )
            for index, point in enumerate(joint_trajectory.points):
                point_summary = ", ".join(
                    f"{name}={position:.6f}"
                    for name, position in zip(
                        joint_trajectory.joint_names, point.positions
                    )
                )
                time_seconds = (
                    point.time_from_start.sec
                    + point.time_from_start.nanosec / 1_000_000_000
                )
                self.get_logger().info(
                    f"Point {index}: t={time_seconds:.6f}s, {point_summary}"
                )
            for joint_index, name in enumerate(joint_trajectory.joint_names):
                positions = [
                    point.positions[joint_index] for point in joint_trajectory.points
                ]
                max_step = max(
                    (
                        abs(current - previous)
                        for previous, current in zip(positions, positions[1:])
                    ),
                    default=0.0,
                )
                self.get_logger().info(
                    f"{name}: max adjacent change={max_step:.6f} rad"
                )

        else:
            self.get_logger().warning(
                f"Planning failed: status={status}, "
                f"MoveIt error code={result.error_code.val}"
            )

    def run_planning_demo(self):
        self.demo_timer.cancel()
        axis = self.get_parameter("axis").value
        distance = self.get_parameter("distance").value
        if axis not in ("x", "y", "z"):
            self.get_logger().warning("Invalid axis: expected 'x', 'y', or 'z'")
            return
        if not math.isfinite(distance):
            self.get_logger().warning("Distance must be finite")
            return
        if distance == 0.0:
            self.get_logger().info("Distance is zero, skipping planning")
            return
        self.request_plan(axis, distance)

    def execute_planned_trajectory(self):
        if self.planned_trajectory is None:
            self.get_logger().warning("No planned trajectory to execute")
            return False

        if self.current_joint_state is None:
            self.get_logger().warning("Cannot execute: joint states unavailable")
            return False

        joint_trajectory = self.planned_trajectory.joint_trajectory
        if not joint_trajectory.points:
            self.get_logger().warning("Cannot execute: trajectory is empty")
            return False

        current_positions = dict(
            zip(self.current_joint_state.name, self.current_joint_state.position)
        )
        start_positions = joint_trajectory.points[0].positions

        for name, planned_start in zip(joint_trajectory.joint_names, start_positions):
            if name not in current_positions:
                self.get_logger().warning(f"Missing joint state: {name}")
                return False
            start_error = abs(current_positions[name] - planned_start)
            if start_error > 0.01:
                self.get_logger().warning(
                    f"Joint {name} moved since planning: "
                    f"error={start_error:.6f} rad; replan required"
                )
                return False

        if not self.execute_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().warning("Trajectory execution server unavailable")
            return False

        self.execution_start_transform = self.get_current_pose()
        if self.execution_start_transform is None:
            return False
        execute_goal = ExecuteTrajectory.Goal()
        execute_goal.trajectory = self.planned_trajectory
        self.execute_goal_future = self.execute_client.send_goal_async(execute_goal)
        self.execute_goal_future.add_done_callback(
            self.execution_goal_response_callback
        )
        return True

    def execution_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warning("Execution goal rejected")
            return
        self.get_logger().info("Execution goal accepted")
        self.execute_result_future = goal_handle.get_result_async()
        self.execute_result_future.add_done_callback(self.execution_result_callback)

    def execution_result_callback(self, future):
        response = future.result()
        status = response.status
        result = response.result
        if status == GoalStatus.STATUS_CANCELED:
            self.get_logger().info("Execution canceled")
            return
        if (
            status != GoalStatus.STATUS_SUCCEEDED
            or result.error_code.val != MoveItErrorCodes.SUCCESS
        ):
            self.get_logger().warning(
                f"Execution failed: status={status}, error={result.error_code.val}"
            )
            return
        self.get_logger().info("Execution succeeded")
        self.start_settle_check()

    def execution_trigger_callback(self, request, response):
        response.success = self.execute_planned_trajectory()
        if response.success:
            response.message = "Execution requested; final result pending"
        else:
            response.message = "Execution request not sent; check node logs"
        return response

    def compare_execution_result(self, actual_transform):
        start = self.execution_start_transform.transform.translation
        actual = actual_transform.transform.translation
        target = self.planned_target_pose.position
        displacement = (actual.x - start.x, actual.y - start.y, actual.z - start.z)
        position_error = math.dist(
            (actual.x, actual.y, actual.z), (target.x, target.y, target.z)
        )

        qa = actual_transform.transform.rotation
        qt = self.planned_target_pose.orientation
        a = (qa.x, qa.y, qa.z, qa.w)
        t = (qt.x, qt.y, qt.z, qt.w)
        norm_a = math.sqrt(sum(v * v for v in a))
        norm_t = math.sqrt(sum(v * v for v in t))
        if norm_a == 0.0 or norm_t == 0.0:
            self.get_logger().warning("Invalid quaternion")
            return
        dot = abs(sum(av * tv for av, tv in zip(a, t)))
        cosine = min(1.0, max(0.0, dot / (norm_a * norm_t)))
        angle_error = 2.0 * math.acos(cosine)

        self.get_logger().info(f"Actual displacement (m): {displacement}")
        self.get_logger().info(
            f"Position error={position_error:.6f} m, "
            f"orientation error={angle_error:.6f} rad"
        )

    def start_settle_check(self):
        self.last_settle_sequence = self.joint_state_sequence
        self.previous_settle_positions = None
        self.stable_sample_count = 0
        self.settle_deadline = time.monotonic() + 5.0
        self.settle_timer = self.create_timer(0.1, self.check_settled_state)

    def check_settled_state(self):
        if time.monotonic() >= self.settle_deadline:
            self.settle_timer.cancel()
            self.get_logger().warning("Timed out waiting for settled state")
            return
        if self.joint_state_sequence == self.last_settle_sequence:
            return

        self.last_settle_sequence = self.joint_state_sequence

        current_positions = dict(
            zip(self.current_joint_state.name, self.current_joint_state.position)
        )

        required_joints = [f"joint{i}" for i in range(1, 7)]
        if any(name not in current_positions for name in required_joints):
            self.previous_settle_positions = None
            self.stable_sample_count = 0
            return

        positions = [current_positions[name] for name in required_joints]

        if self.previous_settle_positions is None:
            self.previous_settle_positions = positions
            return

        max_change = max(
            abs(current - previous)
            for current, previous in zip(positions, self.previous_settle_positions)
        )
        self.previous_settle_positions = positions

        if max_change <= 0.0001:
            self.stable_sample_count += 1
        else:
            self.stable_sample_count = 0

        if self.stable_sample_count < 3:
            return

        if self.stable_sample_count == 3:
            self.settled_joint_stamp = self.current_joint_state.header.stamp

        actual_transform = self.get_current_pose()
        if actual_transform is None:
            return

        tf_time = Time.from_msg(actual_transform.header.stamp).nanoseconds
        stable_time = Time.from_msg(self.settled_joint_stamp).nanoseconds

        if tf_time < stable_time:
            return

        self.settle_timer.cancel()
        self.get_logger().info('Joint feedback settled; comparing execution result')
        self.compare_execution_result(actual_transform)


def main(args=None):
    rclpy.init(args=args)
    node = MotionPlanner()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
