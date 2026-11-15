"""Sequence order, exact retraction target and fail/stop-before-next-stage behavior."""
import copy
from unittest.mock import Mock
import pytest
from geometry_msgs.msg import Pose, TransformStamped, Point
import rclpy
from tictactoe_motion.pose_cycle import PoseCycle
from tictactoe_motion.motion_planner import MotionPlanner


def target():
    pose=Pose();pose.position.x=.2;pose.position.y=-.1;pose.position.z=.24;pose.orientation.y=1.
    return pose


class Driver:
    def __init__(self):self.calls=[];self.actual=target()
    def named(self,name):self.calls.append(('named',name));return {'passed':True}
    def pose(self,pose):self.calls.append(('pose',copy.deepcopy(pose)));self.actual=copy.deepcopy(pose);self.actual.position.z+=.00002;return {'passed':True}
    def current_pose(self):return copy.deepcopy(self.actual)
    def linear(self,position):
        self.calls.append(('linear',copy.deepcopy(position)))
        self.actual.position=copy.deepcopy(position);self.actual.position.z-=.00001
        return {'passed':True}


def test_cycle_order_and_retracts_to_saved_upper_without_accumulation():
    driver=Driver();cycle=PoseCycle(target(),.01);stages=[]
    result=cycle.run(driver,on_stage=stages.append)
    assert stages==['zero_start','target','descend','retract','zero_finish']
    assert len(result)==5
    assert driver.calls[0]==('named','zero') and driver.calls[-1]==('named','zero')
    down,up=driver.calls[2][1],driver.calls[3][1]
    assert up.z-down.z==pytest.approx(.01)
    assert up.z==pytest.approx(.24002)
    assert down.x==up.x==.2 and down.y==up.y==-.1


@pytest.mark.parametrize('distance',[0.,-.01,float('nan'),float('inf'),.1])
def test_invalid_distance_rejected_before_motion(distance):
    with pytest.raises(ValueError):PoseCycle(target(),distance)


def test_failure_never_requests_descent_or_return():
    driver=Driver();driver.pose=Mock(return_value={'passed':False})
    with pytest.raises(RuntimeError):PoseCycle(target(),.01).run(driver)
    assert driver.calls==[('named','zero')]


def test_cancel_between_verified_stages_prevents_next_request():
    driver=Driver()
    with pytest.raises(RuntimeError):PoseCycle(target(),.01).run(driver,cancelled=lambda:len(driver.calls)>=2)
    assert len(driver.calls)==2 and not any(kind=='linear' for kind,_ in driver.calls)


def test_vertical_request_keeps_orientation_and_absolute_xyz():
    rclpy.init();node=MotionPlanner()
    try:
        tf=TransformStamped();tf.header.stamp=node.get_clock().now().to_msg();tf.transform.rotation.w=1.
        tf.transform.translation.x=.2;tf.transform.translation.y=-.1;tf.transform.translation.z=.24
        node.get_current_pose=Mock(return_value=tf)
        node.cartesian_planner.request_path=Mock(return_value=True)
        assert node.cartesian_planner.request_linear_position(Point(x=.2,y=-.1,z=.23))
        args=node.cartesian_planner.request_path.call_args
        assert args.kwargs['fixed_height'] is False
        assert args.args[0][0].orientation==args.args[0][1].orientation
        assert args.args[0][1].position.z==.23
    finally:node.destroy_node();rclpy.try_shutdown()


def test_absolute_pose_request_is_plan_only_and_uses_tight_orientation():
    from concurrent.futures import Future
    from sensor_msgs.msg import JointState
    rclpy.init();node=MotionPlanner()
    try:
        node.joint_state_callback(JointState(name=[f'joint{i}' for i in range(1,7)],position=[0.]*6))
        node.move_client.wait_for_server=Mock(return_value=True)
        node.move_client.send_goal_async=Mock(return_value=Future())
        pose=target()
        assert node.request_pose_plan(pose,orientation_tolerance=.001)
        goal=node.move_client.send_goal_async.call_args.args[0]
        assert goal.planning_options.plan_only
        constraint=goal.request.goal_constraints[0]
        assert constraint.position_constraints[0].header.frame_id=='base_link'
        assert constraint.orientation_constraints[0].absolute_z_axis_tolerance==.001
        pose.position.z=.5
        assert node.planned_target_pose.position.z==.24
    finally:node.cancel_planning();node.destroy_node();rclpy.try_shutdown()


def test_named_driver_checks_stop_after_async_fk_before_planning():
    from simulation_support import SimulationHarness
    driver=SimulationHarness.__new__(SimulationHarness)
    driver.node=Mock()
    stopped=[False]
    driver.motion_guard=lambda:stopped[0]
    def fk(name):
        stopped[0]=True
        return {},target()
    driver.named_target=fk
    with pytest.raises(RuntimeError):driver.named('zero')
    driver.node.request_joint_plan.assert_not_called()


def test_driver_rechecks_stop_before_execution_service():
    from simulation_support import SimulationHarness
    driver=SimulationHarness.__new__(SimulationHarness)
    driver.motion_guard=lambda:True
    driver.call=Mock()
    with pytest.raises(RuntimeError):driver.execute()
    driver.call.assert_not_called()
