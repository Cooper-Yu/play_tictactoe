"""Shared motion orchestration for simulation and real hardware."""

import copy
import time
from pathlib import Path

import rclpy
from moveit_msgs.srv import GetPositionFK
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_srvs.srv import Trigger

from tictactoe_motion.basic_motion.joint_motion.plan import named_target
from tictactoe_motion.bringup.motion_demo import MotionDemo
from tictactoe_motion.basic_motion.motion_primitives import (
    CartesianMotion,
    JointMotion,
    PoseMotion,
)
from tictactoe_motion.trajectory_motion.trajectory_planner import MotionPlanner
from tictactoe_motion.basic_motion.pose_motion.check_result import verify_pose_result
from tictactoe_motion.pose_recording.pose_recording_demo import PoseRecordingDemo
from tictactoe_motion.trajectory_motion.trajectory_checks import check_trajectory
from tictactoe_motion.trajectory_motion.trajectory_executor import run_trajectory


class MotionDriver:
    """! @brief Compose motion primitives and coordinate planning, execution, and recording."""

    def __init__(self, output, install_signal_handlers, *, client_name):
        self.output = Path(output).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        from rclpy.signals import SignalHandlerOptions
        rclpy.init(signal_handler_options=None if install_signal_handlers else SignalHandlerOptions.NO)
        self.executor = SingleThreadedExecutor()
        self.node = MotionPlanner()
        self.node.get_logger().set_level(rclpy.logging.LoggingSeverity.WARN)
        self.motion = MotionDemo(self.node)
        self.recording = PoseRecordingDemo(self.node)
        self.client = Node(client_name, use_global_arguments=False)
        self.executor.add_node(self.node)
        self.executor.add_node(self.client)
        self.execution = self.node.trajectory_executor
        self.cartesian_motion = CartesianMotion(self)
        self.pose_motion = PoseMotion(self)
        self.joint_motion = JointMotion(self)
        self.services = {}
        self.fk_client = self.client.create_client(GetPositionFK, '/compute_fk')
        self.samples = []
        self.results = []

    def until(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError('motion condition timed out')
            self.executor.spin_once(timeout_sec=0.02)

    def result(self, future, timeout=20):
        self.until(future.done, timeout)
        return future.result()

    def call(self, name, success=True):
        if name not in self.services:
            self.services[name] = self.client.create_client(Trigger, '/' + name)
        service = self.services[name]
        self.until(service.service_is_ready)
        response = self.result(service.call_async(Trigger.Request()))
        assert response.success == success, (name, response.message)
        return response

    def parameters(self, **values):
        results = self.node.set_parameters([Parameter(name, value=value) for name, value in values.items()])
        assert all(result.successful for result in results), results

    def fk(self, joints):
        self.until(self.fk_client.service_is_ready)
        request = GetPositionFK.Request()
        request.header.frame_id = 'base_link'
        request.fk_link_names = ['link6']
        request.robot_state.joint_state = copy.deepcopy(self.node.current_joint_state)
        state = request.robot_state.joint_state
        state.position = [float(joints.get(name, angle)) for name, angle in zip(state.name, state.position)]
        request.robot_state.is_diff = True
        response = self.result(self.fk_client.call_async(request))
        assert response.error_code.val == 1, response.error_code.val
        return response.pose_stamped[0].pose

    def named_target(self, name):
        return named_target(self, name)

    def check_motion_guard(self):
        guard = getattr(self, 'motion_guard', None)
        if guard is not None and guard():
            raise RuntimeError('Sequence cancelled; no further motion request allowed')

    def named(self, name):
        return self.joint_motion.named(name)

    def current_pose(self):
        return self.node.cartesian_planner.start_pose()

    def verified_pose_result(self, result):
        return verify_pose_result(result, self.node.settings)

    def pose(self, target):
        return self.pose_motion.move(target)

    def linear(self, target_position, *, speed=None, allow_excursion_retry=False):
        return self.cartesian_motion.linear(
            target_position, speed=speed, allow_excursion_retry=allow_excursion_retry
        )


    def path(self, poses, excursion_limit=0.5, *, speed=None, allow_plan_retry=False):
        """Execute an XY stroke at the achieved drawing height and orientation."""
        return self.cartesian_motion.path(
            poses, excursion_limit, speed=speed, allow_plan_retry=allow_plan_retry
        )

    def guard(self, limit=0.5):
        return check_trajectory(self.node.planned_trajectory, limit)

    def execute(self, timeout=45):
        return run_trajectory(self, timeout)

    def record(self, name):
        self.parameters(record_name=name)
        self.call('record_pose')
        self.until(lambda: self.recording.last_status.get('state') in ('saved', 'failed'), 10)
        assert self.recording.last_status['state'] == 'saved', self.recording.last_status
        return self.recording.recorder.get_pose(name)

    def replay(self, name):
        return self.joint_motion.replay(name)

    def close(self):
        if self.execution.is_executing:
            self.execution.stop.request()
            try:
                self.until(lambda: not self.execution.is_executing, 8)
            except TimeoutError:
                print('STOP_UNCONFIRMED: motion remains blocked', flush=True)
        self.recording.close()
        self.executor.remove_node(self.node)
        self.executor.remove_node(self.client)
        self.node.destroy_node()
        self.client.destroy_node()
        self.executor.shutdown()
        rclpy.try_shutdown()
