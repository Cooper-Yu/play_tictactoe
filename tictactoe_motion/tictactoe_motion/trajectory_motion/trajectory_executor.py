from rclpy.action import ActionClient
import copy
from moveit_msgs.action import ExecuteTrajectory
from action_msgs.msg import GoalStatus
from moveit_msgs.msg import MoveItErrorCodes
import time
import math
from tictactoe_motion.trajectory_motion.motion_stop import MotionStop
from tictactoe_motion.trajectory_motion.trajectory_result_checker import TrajectoryResultChecker


class TrajectoryExecutor:
    """! @brief Send trajectories and keep execution active through verification."""

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
        self.result_checker = TrajectoryResultChecker(
            node, self._verify_execution, self.stop.fail
        )

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
        self.result_checker.start()

    def _verify_execution(self, actual_transform):
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
        self.last_comparison = self.result_checker.compare(
            actual_transform,
            self.execution_start_transform,
            self.planned_target_pose,
            self.target_joint_positions,
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


def run_trajectory(driver, timeout=45):
    """Trigger execution and collect the pose samples and final comparison."""
    driver.check_motion_guard()
    driver.samples = []
    last_stamp = None
    end = driver.node.planned_trajectory.joint_trajectory.points[-1].time_from_start
    planned_duration = end.sec + end.nanosec * 1e-9
    if not math.isfinite(planned_duration):
        raise ValueError('Planned trajectory duration must be finite')
    if planned_duration > 120:
        raise ValueError('Planned trajectory exceeds the 120-second duration limit')
    timeout = max(timeout, 2 * planned_duration + 10)
    started = time.monotonic()
    print(f'EXECUTE planned_duration={planned_duration:.3f}s wall_budget={timeout:.3f}s', flush=True)
    driver.call('execute_planned_trajectory')
    deadline = time.monotonic() + timeout
    while driver.execution.is_executing:
        assert time.monotonic() < deadline, 'execution did not finish'
        driver.executor.spin_once(timeout_sec=0.02)
        transform = driver.node.get_current_pose()
        if transform is None:
            continue
        stamp = (transform.header.stamp.sec, transform.header.stamp.nanosec)
        if stamp == last_stamp:
            continue
        last_stamp = stamp
        p = transform.transform.translation
        q = transform.transform.rotation
        driver.samples.append({'stamp': list(stamp), 'xyz': [p.x, p.y, p.z],
                             'xyzw': [q.x, q.y, q.z, q.w]})
    result = copy.deepcopy(driver.execution.last_comparison)
    assert result is not None, driver.execution.stop.status
    driver.results.append({
        'comparison': result,
        'samples': copy.deepcopy(driver.samples),
        'planned_duration_s': planned_duration,
        'wall_duration_s': time.monotonic() - started,
    })
    return result
