from rclpy.node import Node
from sensor_msgs.msg import JointState
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from tf2_ros import TransformException
from geometry_msgs.msg import Pose
import copy
import math
import time
from moveit_msgs.action import MoveGroup
from shape_msgs.msg import SolidPrimitive
from moveit_msgs.msg import PositionConstraint, OrientationConstraint, Constraints, JointConstraint
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus
from moveit_msgs.msg import MoveItErrorCodes
from tictactoe_motion.trajectory_executor import TrajectoryExecutor
from tictactoe_motion.configuration import declare_settings
from tictactoe_motion.cartesian_planner import CartesianPlanner


class MotionPlanner(Node):
    def __init__(self):
        super().__init__("motion_planner")
        self.settings = declare_settings(self)
        self.current_joint_state = None
        self.planned_trajectory = None
        self.planned_target_pose = None
        self.planned_target_joints = None
        self.planned_record_name = None
        self.is_planning = False
        self.plan_generation = 0
        self.plan_goal_handle = None
        self.is_recording = False
        self.last_joint_state_received = None
        self.feedback_timing = dict(last_gap_s=None, max_gap_s=0., gap_ended_at_s=None,
                                    source_stamp_delta_s=None)
        self.joint_state_subscription = self.create_subscription(
            JointState, self.settings["joint_states_topic"], self.joint_state_callback, 10
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.move_client = ActionClient(self, MoveGroup, self.settings["move_action_name"])
        self.trajectory_executor = TrajectoryExecutor(self)

        self.declare_parameter("axis", "x")
        self.declare_parameter("distance", 0.0)
        self.declare_parameter("velocity_scaling", 0.1)
        self.declare_parameter("acceleration_scaling", 0.1)
        self.declare_parameter('dx', 0.0)
        self.declare_parameter('dy', 0.0)
        self.cartesian_planner = CartesianPlanner(self)
        self.joint_state_sequence = 0

    def destroy_node(self):
        """! @brief Release action waitables before destroying their ROS node/context."""
        cartesian = getattr(self, 'cartesian_planner', None)
        if cartesian is not None:
            cartesian.close()
        recording = getattr(self, 'pose_recording_demo', None)
        if recording is not None:
            recording.close()
        execution = getattr(self, 'trajectory_executor', None)
        if execution is not None:
            execution.stop.close()
            execution.execute_client.destroy()
        client = getattr(self, 'move_client', None)
        if client is not None:
            client.destroy()
        listener = getattr(self, 'tf_listener', None)
        if listener is not None:
            listener.unregister()
        return super().destroy_node()

    def joint_state_callback(self, msg):
        now = time.monotonic()
        if self.last_joint_state_received is not None:
            gap = now-self.last_joint_state_received
            old = self.current_joint_state.header.stamp
            new = msg.header.stamp
            self.feedback_timing.update(
                last_gap_s=gap, max_gap_s=max(gap, self.feedback_timing['max_gap_s']),
                gap_ended_at_s=now,
                source_stamp_delta_s=(new.sec-old.sec)+(new.nanosec-old.nanosec)*1e-9)
        self.current_joint_state = msg
        self.joint_state_sequence += 1
        self.last_joint_state_received = now

    def feedback_snapshot(self, now=None):
        """! @brief Observe reception/source timing without changing the freshness gate.

        Reception gaps include executor scheduling delay. Source age uses the ROS
        clock and can also reflect clock mismatch; neither alone proves network loss.
        """
        now = time.monotonic() if now is None else now
        received = self.last_joint_state_received
        source_age = None
        if self.current_joint_state is not None:
            stamp = self.current_joint_state.header.stamp
            source_age = self.get_clock().now().nanoseconds*1e-9-stamp.sec-stamp.nanosec*1e-9
        return dict(self.feedback_timing, sequence=self.joint_state_sequence,
                    received_at_s=received, receipt_age_s=None if received is None else now-received,
                    source_age_s=source_age, limit_s=self.settings['feedback_max_age'])

    def feedback_is_fresh(self, max_age=None):
        """! @brief Check reception age using the monotonic clock, not ROS timestamps."""
        if max_age is None:
            max_age = self.settings["feedback_max_age"]
        return (
            self.current_joint_state is not None
            and self.last_joint_state_received is not None
            and time.monotonic() - self.last_joint_state_received <= max_age
        )

    def invalidate_plan(self):
        """! @brief Remove a pending trajectory and its target metadata."""
        self.plan_generation += 1
        self.planned_trajectory = None
        self.planned_target_pose = None
        self.planned_target_joints = None
        self.planned_record_name = None

    def cancel_planning(self):
        """! @brief Discard pending plans and cancel this client's known plan-only goal."""
        self.invalidate_plan()
        self.is_planning = False
        cartesian = getattr(self, 'cartesian_planner', None)
        if cartesian is not None:
            cartesian.cancel()
        handle = self.plan_goal_handle
        self.plan_goal_handle = None
        if handle is not None:
            try:
                handle.cancel_goal_async()
            except Exception as error:
                self.get_logger().warning(f"Plan cancellation unavailable; result discarded: {error}")

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

        goal.request.group_name = self.settings["planning_group"]
        goal.request.allowed_planning_time = self.settings["planning_time"]
        goal.request.max_velocity_scaling_factor = velocity_scaling
        goal.request.max_acceleration_scaling_factor = acceleration_scaling
        goal.request.num_planning_attempts = self.settings["planning_attempts"]

        goal.request.start_state.joint_state = current_joint_state
        goal.request.start_state.is_diff = True

        position_constraint = PositionConstraint()
        position_constraint.header.frame_id = "base_link"
        position_constraint.link_name = "link6"
        position_constraint.weight = 1.0

        region = SolidPrimitive()
        region.type = SolidPrimitive.SPHERE
        region.dimensions = [self.settings["position_tolerance"]]

        region_pose = Pose()
        region_pose.position = target_pose.position
        region_pose.orientation.w = 1.0

        position_constraint.constraint_region.primitives = [region]
        position_constraint.constraint_region.primitive_poses = [region_pose]

        orientation_constraint = OrientationConstraint()
        orientation_constraint.header.frame_id = "base_link"
        orientation_constraint.link_name = "link6"
        orientation_constraint.orientation = target_pose.orientation

        orientation_constraint.absolute_x_axis_tolerance = self.settings["orientation_tolerance"]
        orientation_constraint.absolute_y_axis_tolerance = self.settings["orientation_tolerance"]
        orientation_constraint.absolute_z_axis_tolerance = self.settings["orientation_tolerance"]
        orientation_constraint.weight = 1.0

        target_constraints = Constraints()
        target_constraints.position_constraints = [position_constraint]
        target_constraints.orientation_constraints = [orientation_constraint]

        goal.request.goal_constraints = [target_constraints]

        goal.planning_options.plan_only = True
        return goal

    def request_joint_plan(self, joint_positions, target_pose, record_name=None):
        """! @brief Plan, without executing, a return to a recorded joint configuration."""
        if self.is_planning or self.is_recording or self.trajectory_executor.is_executing:
            self.get_logger().warning("Cannot plan return: another task is in progress")
            return False
        self.invalidate_plan()
        if not self.feedback_is_fresh():
            self.get_logger().warning("Cannot plan return: fresh joint feedback unavailable")
            return False
        names = [f"joint{i}" for i in range(1, 7)]
        if any(name not in joint_positions for name in names):
            self.get_logger().warning("Return target must contain joint1 through joint6")
            return False
        if not all(math.isfinite(joint_positions[name]) for name in names):
            self.get_logger().warning("Return joint positions must be finite")
            return False
        # Reuse the existing request settings, then replace only the goal constraints.
        goal = self.build_planning_goal(target_pose, copy.deepcopy(self.current_joint_state))
        if goal is None:
            return False
        constraints = Constraints()
        for name in names:
            constraint = JointConstraint()
            constraint.joint_name = name
            constraint.position = float(joint_positions[name])
            constraint.tolerance_above = self.settings["joint_goal_tolerance"]
            constraint.tolerance_below = self.settings["joint_goal_tolerance"]
            constraint.weight = 1.0
            constraints.joint_constraints.append(constraint)
        goal.request.goal_constraints = [constraints]
        if not self.move_client.wait_for_server(timeout_sec=self.settings["action_server_timeout"]):
            self.get_logger().warning("MoveIt action server unavailable")
            return False
        self.planned_target_pose = copy.deepcopy(target_pose)
        self.planned_target_joints = {name: joint_positions[name] for name in names}
        self.planned_record_name = record_name
        self.is_planning = True
        try:
            self.send_goal_future = self.move_client.send_goal_async(goal)
            generation = self.plan_generation
            self.send_goal_future.add_done_callback(
                lambda future: self.goal_response_callback(future, generation)
            )
        except Exception as error:
            self.is_planning = False
            self.invalidate_plan()
            self.get_logger().error(f"Failed to send return planning request: {error}")
            return False
        return True

    def request_plan(self, axis, distance):
        current = self.get_current_pose()
        if current is None:
            return False
        return self.request_pose_plan(self.calculate_target_pose(current, axis, distance))

    def request_pose_plan(self, target_pose, orientation_tolerance=None):
        """! @brief Plan only to an absolute base_link tool pose from fresh arm feedback."""
        if self.is_recording or self.is_planning or self.trajectory_executor.is_executing:
            self.get_logger().warning("Cannot plan pose: another task is in progress")
            return False
        self.invalidate_plan()
        if not self.feedback_is_fresh():
            self.get_logger().warning("Cannot plan pose: fresh joint states unavailable")
            return False
        p, q = target_pose.position, target_pose.orientation
        if not all(math.isfinite(v) for v in (p.x, p.y, p.z, q.x, q.y, q.z, q.w)) or sum(v*v for v in (q.x,q.y,q.z,q.w)) < 1e-12:
            self.get_logger().warning("Invalid target pose")
            return False
        goal = self.build_planning_goal(target_pose, copy.deepcopy(self.current_joint_state))
        if goal is None:
            return False
        if orientation_tolerance is not None:
            if not math.isfinite(orientation_tolerance) or orientation_tolerance <= 0:
                self.get_logger().warning("Invalid requested orientation tolerance")
                return False
            for constraint in goal.request.goal_constraints[0].orientation_constraints:
                constraint.absolute_x_axis_tolerance = orientation_tolerance
                constraint.absolute_y_axis_tolerance = orientation_tolerance
                constraint.absolute_z_axis_tolerance = orientation_tolerance
        if not self.move_client.wait_for_server(timeout_sec=self.settings["action_server_timeout"]):
            self.get_logger().warning("MoveIt action server unavailable")
            return False
        self.planned_target_pose = copy.deepcopy(target_pose)
        self.is_planning = True
        try:
            self.send_goal_future = self.move_client.send_goal_async(goal)
            generation = self.plan_generation
            self.send_goal_future.add_done_callback(
                lambda future: self.goal_response_callback(future, generation)
            )
        except Exception as error:
            self.is_planning = False
            self.invalidate_plan()
            self.get_logger().error(f"Failed to send planning request: {error}")
            return False
        return True

    def goal_response_callback(self, future, generation=None):
        if generation is None:
            generation = self.plan_generation
        if generation != self.plan_generation:
            try:
                handle = future.result()
                if handle.accepted:
                    handle.cancel_goal_async()
            except Exception as error:
                self.get_logger().warning(f"Discarded plan response: {error}")
            return
        try:
            goal_handle = future.result()
        except Exception as error:
            self.is_planning = False
            self.get_logger().error(
                f"Failed to receive planning goal response: {error}"
            )
            return
        if not goal_handle.accepted:
            self.is_planning = False
            self.get_logger().warning("Planning goal rejected")
            return
        self.plan_goal_handle = goal_handle
        self.get_logger().info("Planning goal accepted")
        try:
            self.result_future = goal_handle.get_result_async()
            self.result_future.add_done_callback(
                lambda result: self.planning_result_callback(result, generation)
            )
        except Exception as error:
            self.is_planning = False
            self.get_logger().error(f"Failed to request planning result: {error}")
            return

    def planning_result_callback(self, future, generation=None):
        if generation is not None and generation != self.plan_generation:
            return
        self.plan_goal_handle = None
        self.is_planning = False
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"Failed to receive planning result: {error}")
            return

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
