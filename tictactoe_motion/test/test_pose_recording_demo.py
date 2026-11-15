"""Recording and return orchestration checks with no robot motion."""

import copy
import json
import time
from unittest.mock import Mock

import pytest
import rclpy
from geometry_msgs.msg import Pose, TransformStamped
from rclpy.parameter import Parameter
from sensor_msgs.msg import JointState
from std_srvs.srv import Trigger

from tictactoe_motion.motion_planner import MotionPlanner
from tictactoe_motion.pose_recorder import PoseRecorder
from tictactoe_motion.pose_recording_demo import PoseRecordingDemo


@pytest.fixture
def demo(tmp_path):
    path = tmp_path / "poses_sim.json"
    rclpy.init(args=["--ros-args", "-p", f"poses_file:={path}", "-p", "environment:=sim"])
    node = MotionPlanner()
    recording = PoseRecordingDemo(node)
    try:
        yield node, recording, path
    finally:
        recording.close()
        node.destroy_node()
        rclpy.try_shutdown()


def invoke(callback):
    return callback(Trigger.Request(), Trigger.Response())


def feedback(node, tick, angle=0.0, transform=True):
    state = JointState()
    state.header.stamp.sec = tick
    state.name = [f"joint{i}" for i in range(1, 7)]
    state.position = [angle] * 6
    node.joint_state_callback(state)
    tf = TransformStamped()
    tf.header = copy.deepcopy(state.header)
    tf.header.frame_id = "base_link"
    tf.child_frame_id = "link6"
    tf.transform.translation.x = 0.2
    tf.transform.translation.z = 0.21
    tf.transform.rotation.w = 1.0
    if transform:
        node.tf_buffer.set_transform(tf, "pytest")
    return state, tf


def capture(node, recording):
    assert invoke(recording.record_callback).success
    for tick in range(1, 5):
        feedback(node, tick)
        recording._capture_tick()
    assert recording.last_status["state"] == "saved"


def test_capture_persists_time_matched_snapshot(demo):
    node, recording, path = demo
    capture(node, recording)
    data = json.loads(path.read_text())
    assert data["A"]["joint_state"]["stamp"] == {"sec": 4, "nanosec": 0}
    assert data["A"]["pose_stamped"]["header"]["stamp"] == {"sec": 4, "nanosec": 0}
    assert not node.is_recording
    assert recording.capture_timer is None


def test_optional_observer_gate_waits_for_new_settled_snapshot(demo):
    node, recording, path = demo
    recording.capture_ready = lambda snapshot: snapshot.header.stamp.sec >= 6
    assert invoke(recording.record_callback).success
    for tick in range(1, 6):
        feedback(node, tick)
        recording._capture_tick()
    assert node.is_recording
    assert not path.exists()
    feedback(node, 6)
    recording._capture_tick()
    assert not node.is_recording
    data = json.loads(path.read_text())
    assert data['A']['joint_state']['stamp']['sec'] == 6
    assert data['A']['pose_stamped']['header']['stamp']['sec'] == 6


def test_repeated_timestamp_cannot_fake_settling(demo):
    node, recording, path = demo
    assert invoke(recording.record_callback).success
    for _ in range(6):
        feedback(node, 1)
        recording._capture_tick()
    assert node.is_recording
    assert not path.exists()


def test_movement_resets_stability(demo):
    node, recording, path = demo
    assert invoke(recording.record_callback).success
    for tick in range(1, 7):
        feedback(node, tick, angle=0.01 * tick)
        recording._capture_tick()
    assert recording.stable_count == 0
    assert not path.exists()


def test_missing_exact_time_tf_waits_without_writing(demo):
    node, recording, path = demo
    assert invoke(recording.record_callback).success
    for tick in range(1, 5):
        feedback(node, tick, transform=False)
        recording._capture_tick()
    assert node.is_recording
    assert not path.exists()


def test_stale_feedback_is_not_recorded(demo):
    node, recording, path = demo
    assert invoke(recording.record_callback).success
    feedback(node, 1)
    node.last_joint_state_received = time.monotonic() - 2
    recording._capture_tick()
    assert recording.previous_positions is None
    assert not path.exists()


def test_capture_timeout_and_cancel_release_only_capture(demo):
    node, recording, path = demo
    assert invoke(recording.record_callback).success
    recording.capture_deadline = time.monotonic() - 1
    recording._capture_tick()
    assert recording.last_status["state"] == "failed"
    assert not node.is_recording
    assert invoke(recording.record_callback).success
    assert invoke(recording.cancel_callback).success
    assert not node.is_recording
    assert not path.exists()


@pytest.mark.parametrize("busy", ["planning", "execution", "recording"])
def test_capture_rejects_busy_tasks(demo, busy):
    node, recording, path = demo
    node.is_planning = busy == "planning"
    node.trajectory_executor.is_executing = busy == "execution"
    node.is_recording = busy == "recording"
    assert not invoke(recording.record_callback).success
    assert not path.exists()


def test_capture_blocks_planning_and_execution(demo):
    node, recording, _ = demo
    assert invoke(recording.record_callback).success
    assert not node.request_plan("x", 0.001)
    assert not node.trajectory_executor.execute_planned_trajectory(None, None)


def test_duplicate_name_and_explicit_overwrite(demo):
    node, recording, path = demo
    capture(node, recording)
    original = path.read_bytes()
    assert not invoke(recording.record_callback).success
    assert path.read_bytes() == original
    node.set_parameters([Parameter("overwrite", value=True)])
    capture(node, recording)
    assert recording.last_status["state"] == "saved"


def test_write_failure_preserves_disk_and_memory(demo, monkeypatch):
    node, recording, path = demo
    capture(node, recording)
    original = path.read_bytes()
    before = copy.deepcopy(recording.recorder.poses)
    node.set_parameters([Parameter("record_name", value="B")])
    monkeypatch.setattr(PoseRecorder, "save_to_file", Mock(side_effect=OSError("disk full")))
    assert invoke(recording.record_callback).success
    for tick in range(5, 9):
        feedback(node, tick)
        recording._capture_tick()
    assert recording.last_status["state"] == "failed"
    assert not node.is_recording
    assert path.read_bytes() == original
    assert recording.recorder.poses == before


def test_load_select_and_delete_invalidate_targets(demo):
    node, recording, path = demo
    capture(node, recording)
    assert invoke(recording.load_callback).success
    assert recording.loaded_pose["name"] == "A"
    node.planned_trajectory = object()
    assert invoke(recording.delete_callback).success
    assert recording.loaded_pose is None
    assert node.planned_trajectory is None
    assert json.loads(path.read_text()) == {}
    assert not invoke(recording.return_callback).success


def test_failed_load_invalidates_old_selection(demo):
    node, recording, _ = demo
    capture(node, recording)
    assert invoke(recording.load_callback).success
    node.set_parameters([Parameter("record_name", value="missing")])
    assert not invoke(recording.load_callback).success
    assert recording.loaded_pose is None


def test_get_pose_returns_independent_copy(demo):
    node, recording, _ = demo
    capture(node, recording)
    selected = recording.recorder.get_pose("A")
    selected["joint_state"]["positions"]["joint1"] = 99.0
    assert recording.recorder.poses["A"]["joint_state"]["positions"]["joint1"] == 0.0


def test_return_goal_uses_joint_constraints_and_never_executes(demo):
    node, recording, _ = demo
    capture(node, recording)
    assert invoke(recording.load_callback).success
    node.move_client.wait_for_server = Mock(return_value=True)
    node.move_client.send_goal_async = Mock(return_value=Mock())
    node.trajectory_executor.execute_client.send_goal_async = Mock()
    assert invoke(recording.return_callback).success
    goal = node.move_client.send_goal_async.call_args.args[0]
    assert goal.planning_options.plan_only
    constraints = goal.request.goal_constraints[0]
    assert len(constraints.joint_constraints) == 6
    assert not constraints.position_constraints
    assert not constraints.orientation_constraints
    assert node.planned_record_name == "A"
    node.trajectory_executor.execute_client.send_goal_async.assert_not_called()


def test_return_verification_checks_joint_and_pose_errors(demo):
    node, recording, _ = demo
    state, tf = feedback(node, 1)
    execution = node.trajectory_executor
    execution.execution_start_transform = tf
    execution.planned_target_pose = Pose()
    execution.planned_target_pose.position.x = 0.2
    execution.planned_target_pose.position.z = 0.21
    execution.planned_target_pose.orientation.w = 1.0
    execution.target_joint_positions = dict(zip(state.name, state.position))
    execution.compare_execution_result(tf)
    assert execution.last_comparison["passed"]
    state.position[0] = 0.002
    node.joint_state_callback(state)
    execution.compare_execution_result(tf)
    assert not execution.last_comparison["passed"]
