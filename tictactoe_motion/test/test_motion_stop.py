"""Software-stop races, terminal states and fresh-feedback gating without motion."""

from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest
import rclpy
from action_msgs.msg import GoalInfo, GoalStatus
from action_msgs.srv import CancelGoal
from moveit_msgs.action import ExecuteTrajectory
from sensor_msgs.msg import JointState
from std_srvs.srv import Trigger
from rclpy.qos import DurabilityPolicy
from unique_identifier_msgs.msg import UUID

from tictactoe_motion.motion_planner import MotionPlanner
from tictactoe_motion.pose_recording_demo import PoseRecordingDemo


def done(value=None, error=None):
    result = Future()
    if error:
        result.set_exception(error)
    else:
        result.set_result(value)
    return result


class Handle:
    accepted = True

    def __init__(self):
        self.goal_id = UUID(uuid=[1] * 16)
        self.result = Future()
        self.cancel = Future()
        self.cancel_goal_async = Mock(return_value=self.cancel)

    def get_result_async(self):
        return self.result


@pytest.fixture
def node(tmp_path):
    rclpy.init(args=['--ros-args', '-p', 'environment:=sim', '-p',
                     f'poses_file:={tmp_path / "test.json"}', '-p', 'settle_samples:=2'])
    instance = MotionPlanner()
    try:
        yield instance
    finally:
        instance.destroy_node()
        rclpy.try_shutdown()


def sample(node, tick, angle=0.0):
    state = JointState()
    state.header.stamp.sec = tick
    state.name = [f'joint{i}' for i in range(1, 7)]
    state.position = [angle] * 6
    node.joint_state_callback(state)
    return state


def active(node, accepted=True):
    execution = node.trajectory_executor
    execution.is_executing = True
    execution.execution_goal_pending = not accepted
    execution.execution_terminal = False
    handle = Handle()
    if accepted:
        execution.execution_goal_response_callback(done(handle))
    return execution, handle


def terminal(execution, handle, status=GoalStatus.STATUS_CANCELED):
    result = ExecuteTrajectory.Result()
    result.error_code.val = 1 if status == GoalStatus.STATUS_SUCCEEDED else -7
    handle.result.set_result(SimpleNamespace(status=status, result=result))


def settle(node, start=1):
    for tick in range(start, start + 3):
        sample(node, tick)
        node.trajectory_executor.stop.tick()


def test_idle_stop_discards_plan_and_cancels_capture(node):
    recording = PoseRecordingDemo(node)
    assert recording.record_callback(Trigger.Request(), Trigger.Response()).success
    node.planned_trajectory = object()
    result = node.trajectory_executor.stop.callback(Trigger.Request(), Trigger.Response())
    assert result.success
    assert node.planned_trajectory is None
    assert not node.is_recording
    assert recording.last_status['state'] == 'canceled'
    assert node.trajectory_executor.stop.status['state'] == 'stopped'
    assert node.trajectory_executor.stop.event_publisher.qos_profile.durability == DurabilityPolicy.VOLATILE


def test_cancel_ack_is_not_stopped_and_duplicates_are_idempotent(node):
    execution, handle = active(node)
    stop = execution.stop
    stop.event_publisher.publish = Mock()
    assert stop.request()
    assert stop.request()
    handle.cancel_goal_async.assert_called_once()
    assert stop.event_publisher.publish.call_count == 1
    assert stop.event_publisher.publish.call_args.args[0].data == 'stop' 
    handle.cancel.set_result(CancelGoal.Response(
        goals_canceling=[GoalInfo(goal_id=handle.goal_id)], return_code=0))
    assert stop.status['state'] == 'cancel_accepted'
    settle(node)
    assert execution.is_executing
    terminal(execution, handle)
    settle(node, 10)
    assert not execution.is_executing
    assert stop.status['state'] == 'stopped'
    assert node.planned_trajectory is None


def test_stop_before_goal_acceptance_cancels_late_handle(node):
    execution, handle = active(node, accepted=False)
    assert execution.stop.request()
    execution.execution_goal_response_callback(done(handle))
    handle.cancel_goal_async.assert_called_once()
    terminal(execution, handle)
    settle(node)
    assert execution.stop.status['state'] == 'stopped'


def test_rejected_pending_execution_still_requires_feedback(node):
    execution, _ = active(node, accepted=False)
    execution.stop.request()
    execution.execution_goal_response_callback(done(SimpleNamespace(accepted=False)))
    assert execution.is_executing
    settle(node)
    assert not execution.is_executing


@pytest.mark.parametrize('status', [GoalStatus.STATUS_SUCCEEDED, GoalStatus.STATUS_ABORTED])
def test_terminal_race_or_abort_still_confirms_stability(node, status):
    execution, handle = active(node)
    execution.stop.request()
    handle.cancel.set_result(CancelGoal.Response(return_code=1))
    assert execution.stop.status['state'] == 'cancel_rejected'
    terminal(execution, handle, status)
    settle(node)
    assert execution.stop.status['state'] == 'stopped'


def test_missing_terminal_times_out_and_keeps_all_motion_blocked(node):
    execution, _ = active(node)
    execution.stop.request()
    settle(node)
    execution.stop.deadline = time.monotonic() - 1
    execution.stop.tick()
    assert execution.is_executing
    assert execution.stop.blocked
    assert not node.request_plan('x', 0.001)
    assert not execution.execute_planned_trajectory(None, None)


@pytest.mark.parametrize('kind', ['repeated', 'stale', 'moving', 'nonfinite', 'incomplete'])
def test_bad_feedback_cannot_release_stop(node, kind):
    execution, handle = active(node)
    execution.stop.request()
    terminal(execution, handle)
    for tick in range(1, 7):
        state = sample(node, 1 if kind == 'repeated' else tick,
                       tick * 0.01 if kind == 'moving' else 0.0)
        if kind == 'stale':
            node.last_joint_state_received = time.monotonic() - 2
        if kind == 'nonfinite':
            state.position[0] = float('nan')
        if kind == 'incomplete':
            state.position = []
        execution.stop.tick()
    assert execution.is_executing
    assert execution.stop.status['state'] != 'stopped'


def test_timeout_can_retry_after_terminal_and_new_feedback(node):
    execution, handle = active(node)
    execution.stop.request()
    execution.stop.deadline = time.monotonic() - 1
    execution.stop.tick()
    terminal(execution, handle)
    assert execution.stop.blocked
    assert execution.stop.request()
    settle(node)
    assert execution.stop.status['state'] == 'stopped'


@pytest.mark.parametrize('stage', ['goal', 'cancel', 'result'])
def test_transport_errors_remain_blocked(node, stage):
    execution, handle = active(node, accepted=stage != 'goal')
    if stage == 'goal':
        execution.execution_goal_response_callback(done(error=RuntimeError('connection lost')))
    else:
        execution.stop.request()
        if stage == 'cancel':
            handle.cancel.set_exception(RuntimeError('connection lost'))
        else:
            handle.result.set_exception(RuntimeError('connection lost'))
    assert execution.stop.blocked
    assert execution.is_executing


def test_stopping_during_normal_settling_replaces_timer(node):
    execution, _ = active(node)
    execution.execution_terminal = True
    execution.start_settle_check()
    old_timer = execution.settle_timer
    execution.stop.request()
    assert old_timer.is_canceled()
    settle(node)
    assert not execution.is_executing


def test_late_cancel_reply_cannot_affect_a_later_execution(node):
    execution, handle = active(node)
    execution.stop.request()
    terminal(execution, handle)
    settle(node)
    execution.is_executing = True
    execution.execution_terminal = False
    handle.cancel.set_exception(RuntimeError('old reply'))
    assert not execution.stop.blocked


def test_late_planning_results_and_acceptance_are_discarded(node):
    generation = node.plan_generation
    node.is_planning = True
    node.planned_trajectory = object()
    node.cancel_planning()
    node.planning_result_callback(done(error=RuntimeError('old result')), generation)
    handle = Handle()
    node.goal_response_callback(done(handle), generation)
    handle.cancel_goal_async.assert_called_once()
    assert node.planned_trajectory is None
    assert not node.is_planning

def test_feedback_stop_can_wait_eight_seconds_without_delaying_cancel(node, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    execution, handle = active(node)
    stop = execution.stop
    assert stop.request(confirmation_timeout=30.)
    assert stop.deadline == 130.
    handle.cancel_goal_async.assert_called_once()
    terminal(execution, handle)
    clock[0] += 8.4
    stop.tick()
    assert execution.is_executing and not stop.blocked
    settle(node)
    assert not execution.is_executing
