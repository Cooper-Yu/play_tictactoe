"""Simulation motion driver and isolated Gazebo preflight."""

import json
import os
import time
from pathlib import Path

import rclpy
from controller_manager_msgs.srv import ListControllers

from tictactoe_driver.motion_driver import MotionDriver
from tictactoe_motion.motion_primitives import JointExcursionError as JointExcursionError


class SimulationDriver(MotionDriver):
    """! @brief Require an isolated simulation graph before running motion."""

    def __init__(self, output, install_signal_handlers=True, client_name='simulation_acceptance'):
        super().__init__(output, install_signal_handlers, client_name=client_name)

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

def write_report(path, report):
    Path(path).write_text(json.dumps(report, indent=2), encoding='utf-8')
