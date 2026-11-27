"""Verify that the driver composes the three motion types and preserves their checks."""

from types import SimpleNamespace
from unittest.mock import Mock, call

from geometry_msgs.msg import Pose
import pytest

from tictactoe_driver import motion_driver
from tictactoe_motion.basic_motion.motion_primitives import (
    CartesianMotion,
    JointExcursionError,
    JointMotion,
    PoseMotion,
)
from tictactoe_driver.real_robot_driver import RealRobotDriver
from tictactoe_driver.simulation_driver import SimulationDriver


@pytest.mark.parametrize("driver_class", [SimulationDriver, RealRobotDriver])
def test_both_drivers_assemble_the_same_motion_types(monkeypatch, tmp_path, driver_class):
    monkeypatch.setattr(motion_driver.rclpy, "init", Mock())
    for name in ("SingleThreadedExecutor", "MotionPlanner", "MotionDemo", "PoseRecordingDemo", "Node"):
        monkeypatch.setattr(motion_driver, name, Mock())
    assert driver_class.__bases__ == (motion_driver.MotionDriver,)
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


def test_motion_progress_preserves_a_quick_plan_until_next_job():
    driver = motion_driver.MotionDriver.__new__(motion_driver.MotionDriver)
    updates = []
    driver.on_motion_progress = updates.append
    driver.node = SimpleNamespace(is_planning=True, planned_trajectory=None)
    driver.execution = SimpleNamespace(is_executing=False)
    driver.reset_motion_progress()

    def receive_plan(**kwargs):
        driver.node.planned_trajectory = object()
        driver.node.is_planning = False

    driver.executor = SimpleNamespace(spin_once=receive_plan)
    driver.until(lambda: not driver.node.is_planning)
    driver.execution.is_executing = True
    driver.report_motion_progress()
    driver.execution.is_executing = False
    driver.report_motion_progress()
    driver.reset_motion_progress()
    driver.report_motion_progress()

    assert updates == [
        dict(phase='planning', planned=False),
        dict(phase='planned', planned=True),
        dict(phase='executing', planned=True),
        dict(phase='idle', planned=True),
        dict(phase='idle', planned=False),
    ]



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
    driver.node.settings = {
        "return_position_tolerance": .001, "return_orientation_tolerance": .01,
    }
    driver.execute.return_value = {
        "passed": True, "position_error_m": .0005, "orientation_error_rad": .005,
    }
    result = CartesianMotion(driver).path([Pose(), waypoint], .4, speed=.2)
    poses = driver.node.cartesian_planner.request_path.call_args.args[0]
    assert result is driver.execute.return_value
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
    driver.node.settings = {
        "return_position_tolerance": .001, "return_orientation_tolerance": .01,
    }
    driver.execute.return_value = {
        "passed": True, "position_error_m": .0005, "orientation_error_rad": .005,
    }
    assert PoseMotion(driver).move(target) is driver.execute.return_value
    assert [entry[0] for entry in driver.mock_calls if entry[0]] == [
        "check_motion_guard", "node.request_pose_plan", "until", "guard",
        "execute",
    ]
    driver.node.request_pose_plan.assert_called_once_with(target, orientation_tolerance=.001)
    driver.guard.assert_called_once_with(2.0)

    driver.execute.return_value["orientation_error_rad"] = .02
    with pytest.raises(AssertionError):
        PoseMotion(driver).move(target)
    assert driver.execute.return_value["passed"] is False


def test_failed_pose_plan_validation_discards_the_trajectory_before_execution():
    driver = Mock()
    validate = Mock(side_effect=RuntimeError("Tool attitude outside entry tolerance"))

    with pytest.raises(RuntimeError, match="outside entry tolerance"):
        PoseMotion(driver).move(Pose(), validate_plan=validate)

    validate.assert_called_once_with(driver.node.planned_trajectory)
    driver.node.invalidate_plan.assert_called_once_with()
    driver.execute.assert_not_called()


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


@pytest.mark.parametrize("driver_class", [SimulationDriver, RealRobotDriver])
@pytest.mark.parametrize(
    "duration, error",
    [(120, None), (121, "120-second"), (float("nan"), "must be finite")],
)
def test_both_drivers_bound_trajectory_duration(driver_class, duration, error):
    driver = driver_class.__new__(driver_class)
    point = SimpleNamespace(time_from_start=SimpleNamespace(sec=duration, nanosec=0))
    trajectory = SimpleNamespace(joint_trajectory=SimpleNamespace(points=[point]))
    driver.node = SimpleNamespace(planned_trajectory=trajectory)
    driver.execution = SimpleNamespace(is_executing=False, last_comparison={"passed": True})
    driver.results = []
    driver.call = Mock()

    if error is None:
        assert driver.execute() == {"passed": True}
        driver.call.assert_called_once_with("execute_planned_trajectory")
    else:
        with pytest.raises(ValueError, match=error):
            driver.execute()
        driver.call.assert_not_called()


def test_named_driver_checks_stop_after_async_fk_before_planning():
    driver=SimulationDriver.__new__(SimulationDriver)
    driver.node=Mock()
    stopped=[False]
    driver.motion_guard=lambda:stopped[0]
    def fk(name):
        stopped[0]=True
        return {}, Pose()
    driver.named_target=fk
    driver.joint_motion = JointMotion(driver)
    with pytest.raises(RuntimeError, match="Sequence cancelled"):driver.named('zero')
    driver.node.request_joint_plan.assert_not_called()


def test_driver_rechecks_stop_before_execution_service():
    driver=SimulationDriver.__new__(SimulationDriver)
    driver.motion_guard=lambda:True
    driver.call=Mock()
    with pytest.raises(RuntimeError):driver.execute()
    driver.call.assert_not_called()


@pytest.mark.parametrize('limit,accepted', [(.5, False), (.7, True)])
def test_linear_excursion_limit_uses_real_trajectory_check(limit, accepted):
    from trajectory_msgs.msg import JointTrajectoryPoint
    from moveit_msgs.msg import RobotTrajectory
    from tictactoe_motion.trajectory_motion.trajectory_checks import check_trajectory
    driver = Mock()
    trajectory = RobotTrajectory()
    trajectory.joint_trajectory.joint_names = [f'joint{i}' for i in range(1, 7)]
    for angle, sec in [(0., 0), (.59066, 1)]:
        point = JointTrajectoryPoint()
        point.positions = [angle, 0., 0., 0., 0., 0.]
        point.time_from_start.sec = sec
        trajectory.joint_trajectory.points.append(point)
    driver.guard.side_effect = lambda value=.5: check_trajectory(trajectory, value)
    driver.node.settings = {'return_position_tolerance': .001,
                            'return_orientation_tolerance': .01}
    driver.execute.return_value = {'passed': True, 'position_error_m': 0.,
                                    'orientation_error_rad': 0.}
    result = CartesianMotion(driver).linear(Pose().position, excursion_limit=limit,
                                            allow_excursion_retry=True)
    assert (result is not None) == accepted
    assert driver.execute.call_count == int(accepted)


@pytest.mark.parametrize('limit', [.49, .71, float('nan'), True])
def test_invalid_linear_excursion_never_plans(limit):
    driver = Mock()
    with pytest.raises(ValueError, match='Linear joint excursion'):
        CartesianMotion(driver).linear(Pose().position, excursion_limit=limit)
    driver.node.cartesian_planner.request_linear_position.assert_not_called()
