"""Verify that the driver composes the three motion types and preserves their checks."""

from unittest.mock import Mock, call

from geometry_msgs.msg import Pose
import pytest

from tictactoe_motion import simulation_driver
from tictactoe_motion.motion_primitives import (
    CartesianMotion,
    JointExcursionError,
    JointMotion,
    PoseMotion,
)
from tictactoe_motion.real_robot_driver import RealRobotDriver
from tictactoe_motion.simulation_driver import SimulationDriver


@pytest.mark.parametrize("driver_class", [SimulationDriver, RealRobotDriver])
def test_both_drivers_assemble_the_same_motion_types(monkeypatch, tmp_path, driver_class):
    monkeypatch.setattr(simulation_driver.rclpy, "init", Mock())
    for name in ("SingleThreadedExecutor", "MotionPlanner", "MotionDemo", "PoseRecordingDemo", "Node"):
        monkeypatch.setattr(simulation_driver, name, Mock())
    driver = driver_class(tmp_path)
    for member, motion_class in (
        (driver.cartesian_motion, CartesianMotion),
        (driver.pose_motion, PoseMotion),
        (driver.joint_motion, JointMotion),
    ):
        assert isinstance(member, motion_class)
        assert member.driver is driver

    xyz = Pose().position
    pose = Pose()
    for member, method, public_method, args, kwargs in (
        (driver.cartesian_motion, "linear", driver.linear, (xyz,), {"speed": .2}),
        (driver.cartesian_motion, "path", driver.path, ([pose], .4), {"allow_plan_retry": True}),
        (driver.pose_motion, "move", driver.pose, (pose,), {}),
        (driver.joint_motion, "named", driver.named, ("clear",), {}),
        (driver.joint_motion, "replay", driver.replay, ("A",), {}),
    ):
        method_mock = Mock()
        monkeypatch.setattr(member, method, method_mock)
        assert public_method(*args, **kwargs) is method_mock.return_value
        method_mock.assert_called_once()


def test_cartesian_stroke_uses_achieved_height_and_orientation():
    driver = Mock()
    anchor = Pose()
    anchor.position.z = .206
    anchor.orientation.y = 1.
    driver.current_pose.return_value = anchor
    waypoint = Pose()
    waypoint.position.x = .23
    waypoint.position.y = .12
    waypoint.position.z = .3
    driver.execute.return_value = {"passed": True}
    result = CartesianMotion(driver).path([Pose(), waypoint], .4, speed=.2)
    poses = driver.node.cartesian_planner.request_path.call_args.args[0]
    assert result is driver.verified_pose_result.return_value
    assert len(poses) == 2 and poses[0] == anchor
    assert poses[1].position.z == anchor.position.z
    assert poses[1].orientation == anchor.orientation
    assert (poses[1].position.x, poses[1].position.y) == (.23, .12)
    assert driver.node.cartesian_planner.request_path.call_args.kwargs == {"speed": .2}
    assert driver.check_motion_guard.call_count == 2
    driver.guard.assert_called_once_with(.4)


def test_rejected_linear_plan_can_return_for_retry_without_execution():
    driver = Mock()
    driver.guard.side_effect = JointExcursionError("too far")
    motion = CartesianMotion(driver)
    assert motion.linear(Pose().position, allow_excursion_retry=True) is None
    driver.node.invalidate_plan.assert_called_once_with()
    with pytest.raises(JointExcursionError):
        motion.linear(Pose().position)
    driver.execute.assert_not_called()


def test_pose_motion_checks_the_plan_before_executing():
    driver = Mock()
    target = Pose()
    assert PoseMotion(driver).move(target) is driver.verified_pose_result.return_value
    assert [entry[0] for entry in driver.mock_calls if entry[0]] == [
        "check_motion_guard", "node.request_pose_plan", "until", "guard",
        "execute", "verified_pose_result",
    ]
    driver.node.request_pose_plan.assert_called_once_with(target, orientation_tolerance=.001)
    driver.guard.assert_called_once_with(2.0)


def test_joint_motion_named_and_recorded_targets_use_verified_execution():
    driver = Mock()
    joints, pose = {"joint1": .1}, Pose()
    driver.named_target.return_value = (joints, pose)
    driver.execute.return_value = {"passed": True}
    motion = JointMotion(driver)
    assert motion.named("clear") == {"passed": True}
    driver.node.request_joint_plan.assert_called_once_with(joints, pose, "clear")
    driver.reset_mock()
    assert motion.replay("A") == {"passed": True}
    driver.parameters.assert_called_once_with(record_name="A")
    assert driver.recording.recorder.poses == {}
    assert driver.call.call_args_list == [call("load_pose"), call("plan_return")]
    assert [entry[0] for entry in driver.mock_calls].index("guard") < [
        entry[0] for entry in driver.mock_calls
    ].index("execute")
