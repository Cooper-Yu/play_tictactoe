from rclpy.action import ActionClient
from moveit_msgs.action import ExecuteTrajectory
from action_msgs.msg import GoalStatus
from moveit_msgs.msg import MoveItErrorCodes
import time
from rclpy.time import Time
import math


class TrajectoryExecutor:
    """!
    @brief Execute planned trajectories and verify the settled robot state.

    Handle execution requests and results, wait for joint feedback to settle,
    and compare the final pose with the target pose.
    """

    def __init__(self, node):
        self.node = node
        self.is_executing = False
        self.execute_client = ActionClient(
            self.node, ExecuteTrajectory, "/execute_trajectory"
        )

    def execution_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.is_executing = False
            self.node.get_logger().warning("Execution goal rejected")
            return

        self.node.get_logger().info("Execution goal accepted")
        self.execute_result_future = goal_handle.get_result_async()
        self.execute_result_future.add_done_callback(self.execution_result_callback)

    def execution_result_callback(self, future):
        response = future.result()
        status = response.status
        result = response.result
        if status == GoalStatus.STATUS_CANCELED:
            self.is_executing = False
            self.node.get_logger().info("Execution canceled")
            return
        if (
            status != GoalStatus.STATUS_SUCCEEDED
            or result.error_code.val != MoveItErrorCodes.SUCCESS
        ):
            self.is_executing = False
            self.node.get_logger().warning(
                f"Execution failed: status={status}, error={result.error_code.val}"
            )
            return
        self.node.get_logger().info("Execution succeeded")
        self.start_settle_check()

    def start_settle_check(self):
        self.last_settle_sequence = self.node.joint_state_sequence
        self.previous_settle_positions = None
        self.stable_sample_count = 0
        self.settle_deadline = time.monotonic() + 5.0
        self.settle_timer = self.node.create_timer(0.1, self.check_settled_state)

    def check_settled_state(self):
        if time.monotonic() >= self.settle_deadline:
            self.settle_timer.cancel()
            self.node.get_logger().warning(
                "Timed out waiting for settled state; "
                "execution remains blocked"
            )
            return
        if self.node.joint_state_sequence == self.last_settle_sequence:
            return

        self.last_settle_sequence = self.node.joint_state_sequence

        current_positions = dict(
            zip(
                self.node.current_joint_state.name,
                self.node.current_joint_state.position,
            )
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
            self.settled_joint_stamp = self.node.current_joint_state.header.stamp

        actual_transform = self.node.get_current_pose()
        if actual_transform is None:
            return

        tf_time = Time.from_msg(actual_transform.header.stamp).nanoseconds
        stable_time = Time.from_msg(self.settled_joint_stamp).nanoseconds

        if tf_time < stable_time:
            return

        self.settle_timer.cancel()
        self.node.get_logger().info(
            "Joint feedback settled; comparing execution result"
        )
        try:
            self.compare_execution_result(actual_transform)
        finally:
            self.is_executing = False

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
            self.node.get_logger().warning("Invalid quaternion")
            return
        dot = abs(sum(av * tv for av, tv in zip(a, t)))
        cosine = min(1.0, max(0.0, dot / (norm_a * norm_t)))
        angle_error = 2.0 * math.acos(cosine)

        self.node.get_logger().info(f"Actual displacement (m): {displacement}")
        self.node.get_logger().info(
            f"Position error={position_error:.6f} m, "
            f"orientation error={angle_error:.6f} rad"
        )

    def execute_planned_trajectory(self, planned_trajectory, target_pose):
        if self.is_executing:
            self.node.get_logger().warning(
                "Cannot execute: execution already in progress"
            )
            return False
        if self.node.is_planning:
            self.node.get_logger().warning(
                "Cannot execute: planning is in progress"
            )
            return False
        self.planned_trajectory = planned_trajectory
        self.planned_target_pose = target_pose

        if self.planned_trajectory is None:
            self.node.get_logger().warning("No planned trajectory to execute")
            return False

        if self.node.current_joint_state is None:
            self.node.get_logger().warning("Cannot execute: joint states unavailable")
            return False

        joint_trajectory = self.planned_trajectory.joint_trajectory
        if not joint_trajectory.points:
            self.node.get_logger().warning("Cannot execute: trajectory is empty")
            return False

        current_positions = dict(
            zip(
                self.node.current_joint_state.name,
                self.node.current_joint_state.position,
            )
        )
        start_positions = joint_trajectory.points[0].positions

        for name, planned_start in zip(joint_trajectory.joint_names, start_positions):
            if name not in current_positions:
                self.node.get_logger().warning(f"Missing joint state: {name}")
                return False
            start_error = abs(current_positions[name] - planned_start)
            if start_error > 0.01:
                self.node.get_logger().warning(
                    f"Joint {name} moved since planning: "
                    f"error={start_error:.6f} rad; replan required"
                )
                return False

        if not self.execute_client.wait_for_server(timeout_sec=5.0):
            self.node.get_logger().warning("Trajectory execution server unavailable")
            return False

        self.execution_start_transform = self.node.get_current_pose()
        if self.execution_start_transform is None:
            return False
        execute_goal = ExecuteTrajectory.Goal()
        execute_goal.trajectory = self.planned_trajectory
        self.is_executing = True
        try:
            self.execute_goal_future = self.execute_client.send_goal_async(execute_goal)
            self.execute_goal_future.add_done_callback(
                self.execution_goal_response_callback
            )
        except Exception as error:
            self.is_executing = False
            self.node.get_logger().error(f"Failed to send execution request: {error}")
            return False
        return True
