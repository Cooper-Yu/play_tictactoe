"""Geometry, timing and stop-race checks for Cartesian planning without motion."""
import copy
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import rclpy
from geometry_msgs.msg import Pose, TransformStamped
from moveit_msgs.msg import RobotTrajectory
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint
from tictactoe_motion.cartesian_planner import stretch_timing, polyline_error
from tictactoe_motion.motion_planner import MotionPlanner


def trajectory():
    t = RobotTrajectory()
    t.joint_trajectory.joint_names = [f'joint{i}' for i in range(1, 7)]
    for stamp in (0, 1):
        p = JointTrajectoryPoint(positions=[stamp*0.01]*6, velocities=[0.02]*6, accelerations=[0.03]*6)
        p.time_from_start.sec = stamp
        t.joint_trajectory.points.append(p)
    return t


def test_conservative_timing_and_no_mutation():
    source = trajectory()
    result = stretch_timing(source, 0.1, 0.1, 2.0)
    assert result.joint_trajectory.points[-1].time_from_start.sec == 10
    assert result.joint_trajectory.points[-1].velocities[0] == pytest.approx(0.002)
    assert result.joint_trajectory.points[-1].accelerations[0] == pytest.approx(0.0003)
    assert source.joint_trajectory.points[-1].time_from_start.sec == 1
    source.joint_trajectory.points[-1].time_from_start.sec = 0
    with pytest.raises(ValueError):
        stretch_timing(source, 0.1, 0.1, 2.0)


@pytest.fixture
def planner():
    rclpy.init()
    node = MotionPlanner()
    c = node.cartesian_planner
    state = JointState(name=[f'joint{i}' for i in range(1, 7)], position=[0.0]*6)
    node.joint_state_callback(state)
    tf = TransformStamped()
    tf.header.stamp = node.get_clock().now().to_msg()
    tf.transform.rotation.w = 1.0
    node.get_current_pose = Mock(return_value=tf)
    c.client.service_is_ready = Mock(return_value=True)
    c.fk_client.service_is_ready = Mock(return_value=True)
    c.client.call_async = Mock(return_value=Future())
    try:
        yield node, c
    finally:
        node.cancel_planning()
        node.destroy_node()
        rclpy.try_shutdown()


def test_xy_request_and_stop_discard_late_result(planner):
    n, c = planner
    assert c.request_xy(0.01, -0.02)
    request = c.client.call_async.call_args.args[0]
    assert request.avoid_collisions and request.header.frame_id == 'base_link'
    assert request.waypoints[0].position.x == 0.01
    assert request.waypoints[0].position.y == -0.02
    assert request.waypoints[0].position.z == 0.0
    generation = n.plan_generation
    n.cancel_planning()
    assert c.timer is None and c.future is None
    future = Future()
    future.set_result(SimpleNamespace(error_code=SimpleNamespace(val=1), fraction=1.0, solution=trajectory()))
    c.path_ready(future, generation)
    assert n.planned_trajectory is None


@pytest.mark.parametrize('fraction,code,jump', [(0.9,1,0.01), (1.,-1,0.01), (1.,1,0.2)])
def test_reject_partial_error_and_jump(planner, fraction, code, jump):
    n, c = planner
    assert c.request_xy(0.01,0.01)
    result = trajectory()
    result.joint_trajectory.points[-1].positions = [jump]*6
    f = Future()
    f.set_result(SimpleNamespace(error_code=SimpleNamespace(val=code),fraction=fraction,solution=result))
    c.path_ready(f,n.plan_generation)
    assert not n.is_planning and n.planned_trajectory is None
    assert not c.last_report['accepted']


def test_zero_nonfinite_and_fixed_height(planner):
    n,c = planner
    for dx,dy in [(0.,0.),(float('nan'),0.),(0.,float('inf'))]:
        assert not c.request_xy(dx,dy)
    a=Pose();a.orientation.w=1.0
    b=copy.deepcopy(a);b.position.z=.01
    assert not c.request_path([a,b])
    assert not n.is_planning
    b.position.x=1.0;b.position.z=0.0
    assert polyline_error((.5,.1,0.),[a,b]) == pytest.approx(.1)


def test_closed_path_collapsed_to_start_is_not_accepted(planner):
    from geometry_msgs.msg import PoseStamped
    from tictactoe_motion.drawing_paths import circle_path
    n,c=planner
    start=c.start_pose()
    assert c.request_path(circle_path(start,.01))
    fake=trajectory()
    fake.joint_trajectory.points[-1].positions=[0.0]*6
    response=Future()
    response.set_result(SimpleNamespace(error_code=SimpleNamespace(val=1),fraction=1.,solution=fake))
    fk=Future();fk.set_result(SimpleNamespace(error_code=SimpleNamespace(val=1),pose_stamped=[PoseStamped(pose=start)]))
    c.fk_client.call_async=Mock(return_value=fk)
    c.path_ready(response,n.plan_generation)
    assert n.planned_trajectory is None
    assert 'coverage gap' in c.last_report['reason']


def test_interpolation_matches_endpoint_derivative_order():
    from tictactoe_motion.cartesian_planner import interpolate_joint_segment
    t=trajectory();a,b=t.joint_trajectory.points
    a.velocities=[];b.velocities=[];a.accelerations=[];b.accelerations=[]
    assert interpolate_joint_segment(a,b,.25)==pytest.approx([.0025]*6)
    a.velocities=[0.]*6;b.velocities=[0.]*6
    assert interpolate_joint_segment(a,b,.25)==pytest.approx([.0015625]*6)
    a.accelerations=[0.]*6;b.accelerations=[0.]*6
    assert interpolate_joint_segment(a,b,.25)==pytest.approx([.00103515625]*6)
