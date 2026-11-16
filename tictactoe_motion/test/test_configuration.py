"""Configuration behavior checks without robot hardware or GUI windows."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import rclpy
from geometry_msgs.msg import Pose
from sensor_msgs.msg import JointState
from rclpy.time import Time
from rclpy.parameter import Parameter
from tictactoe_motion.motion_planner import MotionPlanner
from tictactoe_motion.pose_recording_demo import PoseRecordingDemo


@pytest.fixture
def node():
    rclpy.init(args=['--ros-args', '-p', 'planning_time:=2.5', '-p',
                     'position_tolerance:=0.002', '-p', 'orientation_tolerance:=0.02',
                     '-p', 'planning_attempts:=4', '-p', 'settle_samples:=2',
                     '-p', 'joint_goal_tolerance:=0.0002'])
    instance = MotionPlanner()
    try:
        yield instance
    finally:
        instance.destroy_node()
        rclpy.try_shutdown()


def test_configured_constraints_and_read_only_settings(node):
    pose = Pose()
    pose.orientation.w = 1.0
    goal = node.build_planning_goal(pose, JointState())
    assert goal.request.allowed_planning_time == 2.5
    assert goal.request.num_planning_attempts == 4
    constraints = goal.request.goal_constraints[0]
    assert list(constraints.position_constraints[0].constraint_region.primitives[0].dimensions) == [0.002]
    assert constraints.orientation_constraints[0].absolute_z_axis_tolerance == 0.02
    assert goal.planning_options.plan_only
    result = node.set_parameters([Parameter('settle_samples', value=0)])[0]
    assert not result.successful


def test_real_default_has_separate_file_and_never_requests_motion(node, monkeypatch):
    monkeypatch.setattr(PoseRecordingDemo, '_reload', lambda self: None)
    node.move_client.send_goal_async = Mock()
    node.trajectory_executor.execute_client.send_goal_async = Mock()
    demo = PoseRecordingDemo(node)
    try:
        assert demo.environment == 'real'
        assert demo.recorder.poses_file == Path.home() / 'ros2_ws/src/play_tictactoe/data/poses_real.json'
        node.move_client.send_goal_async.assert_not_called()
        node.trajectory_executor.execute_client.send_goal_async.assert_not_called()
    finally:
        demo.close()


@pytest.mark.parametrize('parameter', ['planning_time:=0.0', 'feedback_max_age:=.nan',
                                      'settle_samples:=0', 'return_position_tolerance:=-0.1'])
def test_invalid_settings_rejected_at_startup(parameter):
    rclpy.init(args=['--ros-args', '-p', parameter])
    try:
        with pytest.raises(ValueError):
            MotionPlanner()
    finally:
        rclpy.try_shutdown()

def test_settle_count_and_return_constraints_use_configuration(node, monkeypatch):
    monkeypatch.setattr(PoseRecordingDemo, '_reload', lambda self: None)
    recording = PoseRecordingDemo(node)
    try:
        recording.previous_positions = None
        recording.last_sequence = -1
        recording.last_stamp = None
        recording.stable_count = 0
        recording.snapshot = None
        for tick in range(1, 4):
            state = JointState()
            state.header.stamp = Time(seconds=tick).to_msg()
            state.name = [f'joint{i}' for i in range(1, 7)]
            state.position = [0.0] * 6
            node.joint_state_callback(state)
            recording._observe_feedback()
        assert recording.stable_count == 2
        assert recording.snapshot is not None
        node.move_client.wait_for_server = Mock(return_value=True)
        node.move_client.send_goal_async = Mock(return_value=Mock())
        pose = Pose()
        pose.orientation.w = 1.0
        assert node.request_joint_plan(dict(zip(state.name, state.position)), pose, 'A')
        goal = node.move_client.send_goal_async.call_args.args[0]
        for joint in goal.request.goal_constraints[0].joint_constraints:
            assert joint.tolerance_above == 0.0002
            assert joint.tolerance_below == 0.0002
    finally:
        recording.close()

def test_feedback_diagnostics_preserve_stale_gate_and_distinguish_clocks(node, monkeypatch):
    import tictactoe_motion.motion_planner as planner_module
    clock = Mock()
    clock.now.return_value.nanoseconds = 20_000_000_000
    monkeypatch.setattr(node, 'get_clock', lambda: clock)
    now = [100.0]
    monkeypatch.setattr(planner_module.time, 'monotonic', lambda: now[0])
    empty = node.feedback_snapshot()
    assert empty['receipt_age_s'] is None and empty['source_age_s'] is None
    assert not node.feedback_is_fresh()
    first = JointState()
    first.header.stamp.sec = 19
    node.joint_state_callback(first)
    now[0] = 101.1
    stale = node.feedback_snapshot()
    assert stale['receipt_age_s'] == pytest.approx(1.1)
    assert stale['source_age_s'] == pytest.approx(1.0)
    assert not node.feedback_is_fresh()
    # Reading diagnostics must never renew feedback or loosen the configured limit.
    assert node.last_joint_state_received == 100.0 and stale['limit_s'] == 1.0
    second = JointState()
    second.header.stamp.sec = 19
    second.header.stamp.nanosec = 2_000_000
    node.joint_state_callback(second)
    resumed = node.feedback_snapshot()
    assert resumed['last_gap_s'] == pytest.approx(1.1)
    assert resumed['max_gap_s'] == pytest.approx(1.1)
    assert resumed['source_stamp_delta_s'] == pytest.approx(.002)
    assert resumed['sequence'] == 2 and node.feedback_is_fresh()
    resumed['max_gap_s'] = 0
    assert node.feedback_snapshot()['max_gap_s'] == pytest.approx(1.1)