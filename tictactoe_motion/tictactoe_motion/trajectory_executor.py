from rclpy.action import ActionClient
import copy
from moveit_msgs.action import ExecuteTrajectory
from action_msgs.msg import GoalStatus
from moveit_msgs.msg import MoveItErrorCodes
import time
from rclpy.time import Time
import math
from tictactoe_motion.motion_stop import MotionStop


class TrajectoryExecutor:
    """!
    @brief Execute planned trajectories and verify the settled robot state.

    Handle execution requests and results, wait for joint feedback to settle,
    and compare the final pose with the target pose.
    """

    def __init__(self, node):
        self.node = node
        self.settings = node.settings
        self.is_executing = False
        self.execution_goal_handle = None
        self.execution_goal_pending = False
        self.execution_terminal = True
        self.last_comparison = None
        self.target_joint_positions = None
        self.target_record_name = None
        self.on_verification = None
        self.execute_client = ActionClient(
            self.node, ExecuteTrajectory, self.settings["execute_action_name"]
        )
        self.stop = MotionStop(node, self)

    def execution_goal_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as error:
            self.stop.fail(f"Failed to receive execution goal response: {error}")
            return
        self.execution_goal_pending = False
        if not goal_handle.accepted:
            self.execution_terminal = True
            if self.stop.active:
                self.stop.terminal_received(GoalStatus.STATUS_ABORTED)
                return
            self.is_executing = False
            self.node.get_logger().warning("Execution goal rejected")
            return

        self.execution_goal_handle = goal_handle
        self.node.get_logger().info("Execution goal accepted")
        try:
            self.execute_result_future = goal_handle.get_result_async()
            self.execute_result_future.add_done_callback(
                self.execution_result_callback
            )
            self.stop.cancel_available_goal()
        except Exception as error:
            self.stop.fail(f"Failed to request execution result: {error}")
            return

    def execution_result_callback(self, future):
        try:
            response = future.result()
        except Exception as error:
            self.stop.fail(f"Failed to receive execution result: {error}")
            return
        status = response.status
        result = response.result
        if status not in (
            GoalStatus.STATUS_SUCCEEDED, GoalStatus.STATUS_CANCELED, GoalStatus.STATUS_ABORTED,
        ):
            self.stop.fail(f"Unexpected execution result status: {status}")
            return
        self.execution_terminal = True
        if (self.stop.active or status != GoalStatus.STATUS_SUCCEEDED
                or result.error_code.val != MoveItErrorCodes.SUCCESS):
            self.node.get_logger().info(
                f"Execution ended: status={status}, error={result.error_code.val}"
            )
            self.stop.terminal_received(status)
            return
        self.node.get_logger().info("Execution succeeded")
        self.start_settle_check()

    def start_settle_check(self):
        previous_timer = getattr(self, 'settle_timer', None)
        if previous_timer is not None:
            self.node.destroy_timer(previous_timer)
        self.last_settle_sequence = self.node.joint_state_sequence
        self.previous_settle_positions = None
        self.stable_sample_count = 0
        self.settle_deadline = time.monotonic() + self.settings["settle_timeout"]
        self.settle_timer = self.node.create_timer(self.settings["settle_period"], self.check_settled_state)

    def check_settled_state(self):
        if time.monotonic() >= self.settle_deadline:
            self.settle_timer.cancel()
            self.stop.fail("Timed out waiting for settled state")
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

        if max_change <= self.settings["settle_joint_tolerance"]:
            self.stable_sample_count += 1
        else:
            self.stable_sample_count = 0

        if self.stable_sample_count < self.settings["settle_samples"]:
            return

        if self.stable_sample_count == self.settings["settle_samples"]:
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
        except Exception as error:
            self.last_comparison = {"passed": False, "error": str(error)}
            self.node.get_logger().error(f"Execution verification failed: {error}")
        finally:
            self.is_executing = False
            self.execution_goal_handle = None
        self.stop.publish("idle", "Execution finished; final state checked")
        callback = getattr(self, "on_verification", None)
        if callback is not None:
            callback(self.target_record_name, self.last_comparison)

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
        self.last_comparison = {
            "position_error_m": position_error,
            "orientation_error_rad": angle_error,
            "displacement_m": list(displacement),
        }
        target_joints = getattr(self, "target_joint_positions", None)
        if target_joints is not None:
            state = self.node.current_joint_state
            actual_joints = dict(zip(state.name, state.position))
            joint_errors = {
                name: abs(actual_joints[name] - target)
                for name, target in target_joints.items()
            }
            max_error = max(joint_errors.values())
            passed = (
                max_error <= self.settings["return_joint_tolerance"]
                and position_error <= self.settings["return_position_tolerance"]
                and angle_error <= self.settings["return_orientation_tolerance"]
            )
            self.last_comparison.update(
                joint_errors_rad=joint_errors,
                max_joint_error_rad=max_error,
                passed=passed,
            )
            self.node.get_logger().info(
                f"Return verification {'PASSED' if passed else 'FAILED'}: "
                f"max joint error={max_error:.6f} rad"
            )

    def execute_planned_trajectory(
        self, planned_trajectory, target_pose, target_joint_positions=None,
        target_record_name=None,
    ):
        if getattr(self.node, "is_recording", False):
            self.node.get_logger().warning("Cannot execute: pose recording is in progress")
            return False
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
        self.planned_trajectory = copy.deepcopy(planned_trajectory)
        self.planned_target_pose = copy.deepcopy(target_pose)
        self.target_joint_positions = copy.deepcopy(target_joint_positions)
        self.target_record_name = target_record_name
        self.last_comparison = None

        if self.planned_trajectory is None:
            self.node.get_logger().warning("No planned trajectory to execute")
            return False

        if self.planned_target_pose is None:
            self.node.get_logger().warning("Cannot execute: target pose unavailable")
            return False

        fresh_check = getattr(self.node, "feedback_is_fresh", None)
        if fresh_check is not None and not fresh_check():
            self.node.get_logger().warning("Cannot execute: joint feedback is stale")
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
            if start_error > self.settings["execution_start_tolerance"]:
                self.node.get_logger().warning(
                    f"Joint {name} moved since planning: "
                    f"error={start_error:.6f} rad; replan required"
                )
                return False

        if not self.execute_client.wait_for_server(timeout_sec=self.settings["action_server_timeout"]):
            self.node.get_logger().warning("Trajectory execution server unavailable")
            return False

        self.execution_start_transform = self.node.get_current_pose()
        if self.execution_start_transform is None:
            return False
        execute_goal = ExecuteTrajectory.Goal()
        execute_goal.trajectory = self.planned_trajectory
        self.is_executing = True
        self.execution_goal_handle = None
        self.execution_goal_pending = True
        self.execution_terminal = False
        self.stop.publish('executing', 'Trajectory execution requested')
        try:
            self.execute_goal_future = self.execute_client.send_goal_async(execute_goal)
            self.execute_goal_future.add_done_callback(
                self.execution_goal_response_callback
            )
        except Exception as error:
            self.stop.fail(f"Failed to send execution request: {error}")
            return False
        return True
