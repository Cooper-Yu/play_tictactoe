"""Shared bounded integration support for the Piper Gazebo-only scenarios."""

import copy
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import rclpy
from controller_manager_msgs.srv import ListControllers
from moveit_msgs.srv import GetPositionFK
from rcl_interfaces.srv import GetParameters
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_srvs.srv import Trigger

from tictactoe_motion.motion_demo import MotionDemo
from tictactoe_motion.motion_planner import MotionPlanner
from tictactoe_motion.pose_recording_demo import PoseRecordingDemo


class SimulationHarness:
    """! @brief Exercise the public demo services, refusing hardware or shared ROS graphs."""

    def __init__(self, output):
        self.output = Path(output).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        rclpy.init()
        self.executor = SingleThreadedExecutor()
        self.node = MotionPlanner()
        self.node.get_logger().set_level(rclpy.logging.LoggingSeverity.WARN)
        self.motion = MotionDemo(self.node)
        self.recording = PoseRecordingDemo(self.node)
        self.client = Node('simulation_acceptance', use_global_arguments=False)
        self.executor.add_node(self.node)
        self.executor.add_node(self.client)
        self.execution = self.node.trajectory_executor
        self.services = {}
        self.fk_client = self.client.create_client(GetPositionFK, '/compute_fk')
        self.samples = []
        self.results = []

    def until(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError('simulation condition timed out')
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

    def preflight(self):
        assert os.environ.get('ROS_LOCALHOST_ONLY') == '1'
        assert self.recording.environment == 'sim'
        assert self.node.get_parameter('use_sim_time').value
        assert self.recording.recorder.poses_file.resolve().is_relative_to(self.output)
        self.until(lambda: self.node.feedback_is_fresh() and self.node.tf_buffer.can_transform(
            'base_link', 'link6', rclpy.time.Time()), 45)
        self.until(lambda: {'gazebo', 'move_group'}.issubset(
            {name for name, _ in self.client.get_node_names_and_namespaces()}), 15)
        names = {name for name, _ in self.client.get_node_names_and_namespaces()}
        assert 'gazebo' in names and 'move_group' in names, names
        assert not any('zenoh' in n or 'piper_ctrl' in n for n in names), names
        service = self.client.create_client(ListControllers, '/controller_manager/list_controllers')
        self.until(service.service_is_ready)
        deadline = time.monotonic() + 30.0
        while True:
            response = self.result(service.call_async(ListControllers.Request()))
            states = {controller.name: controller.state for controller in response.controller}
            if states.get('arm_controller') == 'active':
                return states
            assert time.monotonic() < deadline, ('arm controller activation timed out', states)
            pause = time.monotonic() + 0.2
            self.until(lambda: time.monotonic() >= pause, 1.0)

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

    def named(self, name):
        service = self.client.create_client(GetParameters, '/move_group/get_parameters')
        self.until(service.service_is_ready)
        request = GetParameters.Request(names=['robot_description_semantic'])
        xml = self.result(service.call_async(request)).values[0].string_value
        state = ET.fromstring(xml).find(f"group_state[@group='arm'][@name='{name}']")
        assert state is not None, name
        joints = {joint.attrib['name']: float(joint.attrib['value']) for joint in state.findall('joint')}
        assert set(joints) == {f'joint{i}' for i in range(1, 7)}
        assert self.node.request_joint_plan(joints, self.fk(joints), name)
        self.until(lambda: not self.node.is_planning)
        self.guard(2.0)
        result = self.execute()
        assert result.get('passed'), result
        return result

    def guard(self, limit=0.5):
        trajectory = self.node.planned_trajectory
        assert trajectory is not None, 'No accepted plan'
        joints = trajectory.joint_trajectory
        assert set(joints.joint_names) == {f'joint{i}' for i in range(1, 7)}
        assert joints.points
        maximum = max(abs(value - joints.points[0].positions[i])
                      for point in joints.points for i, value in enumerate(point.positions))
        assert maximum < limit, ('excessive joint excursion', maximum)
        previous = -1.0
        for point in joints.points:
            assert len(point.positions) == len(joints.joint_names)
            assert all(math.isfinite(value) for value in point.positions)
            stamp = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9
            assert stamp >= previous
            previous = stamp
        return {'max_joint_excursion_rad': maximum, 'points': len(joints.points), 'duration_s': previous}

    def execute(self, timeout=45):
        self.samples = []
        last_stamp = None
        self.call('execute_planned_trajectory')
        deadline = time.monotonic() + timeout
        while self.execution.is_executing:
            assert time.monotonic() < deadline, 'execution did not finish'
            self.executor.spin_once(timeout_sec=0.02)
            transform = self.node.get_current_pose()
            if transform is None:
                continue
            stamp = (transform.header.stamp.sec, transform.header.stamp.nanosec)
            if stamp == last_stamp:
                continue
            last_stamp = stamp
            p = transform.transform.translation
            q = transform.transform.rotation
            self.samples.append({'stamp': list(stamp), 'xyz': [p.x, p.y, p.z],
                                 'xyzw': [q.x, q.y, q.z, q.w]})
        result = copy.deepcopy(self.execution.last_comparison)
        assert result is not None, self.execution.stop.status
        self.results.append({'comparison': result, 'samples': copy.deepcopy(self.samples)})
        return result

    def record(self, name):
        self.parameters(record_name=name)
        self.call('record_pose')
        self.until(lambda: self.recording.last_status.get('state') in ('saved', 'failed'), 10)
        assert self.recording.last_status['state'] == 'saved', self.recording.last_status
        return self.recording.recorder.get_pose(name)

    def replay(self, name):
        self.parameters(record_name=name)
        self.recording.recorder.poses = {}
        self.call('load_pose')
        self.call('plan_return')
        self.until(lambda: not self.node.is_planning)
        self.guard(2.0)
        result = self.execute()
        assert result.get('passed'), result
        return result

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


def write_report(path, report):
    Path(path).write_text(json.dumps(report, indent=2), encoding='utf-8')