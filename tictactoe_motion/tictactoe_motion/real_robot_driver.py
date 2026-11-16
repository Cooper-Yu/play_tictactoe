"""Real Piper profile over shared bounded planning/execution orchestration."""
import math
from controller_manager_msgs.srv import ListControllers
import rclpy
from tictactoe_motion.simulation_driver import SimulationDriver


def require_real_profile(environment, use_sim_time, names):
    """! @brief Reject simulated graphs and ambiguous motion owners."""
    if environment != 'real' or use_sim_time:
        raise ValueError('Real workstation requires environment=real and use_sim_time=false')
    if any('gazebo' in name for name in names):
        raise ValueError('Gazebo discovered in the real robot domain')
    if names.count('motion_planner') != 1 or names.count('move_group') != 1:
        raise ValueError('Real workstation requires one motion_planner and one move_group')
    if 'piper_ctrl_single_node' not in names or not any('zenoh' in name for name in names):
        raise ValueError('Real Piper driver / platform bridge not discovered')


class RealRobotDriver(SimulationDriver):
    """! @brief Reuse bounded mechanics with a separate hardware-only preflight.

    The simulation preflight remains unchanged. This adapter requires fresh
    wall-clock feedback, one physical controller and one motion owner. It never
    enables hardware or moves on startup.
    """
    def __init__(self, output, install_signal_handlers=False):
        super().__init__(output, install_signal_handlers, client_name='real_localization_workbench')
        self.controller_client = self.client.create_client(ListControllers, '/controller_manager/list_controllers')

    def preflight(self):
        self.until(lambda: self.node.feedback_is_fresh() and self.node.tf_buffer.can_transform(
            'base_link', 'link6', rclpy.time.Time()), 15)
        names = [name for name, _ in self.client.get_node_names_and_namespaces()]
        require_real_profile(self.recording.environment, self.node.get_parameter('use_sim_time').value, names)
        if not self.recording.recorder.poses_file.resolve().is_relative_to(self.output):
            raise ValueError('Real record file must remain inside the real output directory')
        state = self.node.current_joint_state
        positions = dict(zip(state.name, state.position))
        if len(state.name) != len(state.position) or len(positions) != len(state.name):
            raise ValueError('Invalid joint feedback arrays')
        if any(not math.isfinite(positions.get(f'joint{i}', float('nan'))) for i in range(1, 7)):
            raise ValueError('Missing or invalid physical arm joints')
        now = self.node.get_clock().now().nanoseconds*1e-9
        stamp = state.header.stamp.sec+state.header.stamp.nanosec*1e-9
        transform = self.node.get_current_pose()
        tf_stamp = transform.header.stamp.sec+transform.header.stamp.nanosec*1e-9
        if not -.2 <= now-stamp <= 1. or not -.2 <= now-tf_stamp <= 1.:
            raise ValueError('Physical joint / TF timestamps are stale or clocks disagree')
        if self.client.count_publishers('/joint_states') != 1:
            raise ValueError('Expected exactly one physical /joint_states publisher')
        self.until(self.controller_client.service_is_ready, 5)
        response = self.result(self.controller_client.call_async(ListControllers.Request()), 5)
        arm = [controller for controller in response.controller if controller.name == 'arm_controller']
        expected = {f'joint{i}/position' for i in range(1, 7)}
        if len(arm) != 1 or arm[0].state != 'active' or set(arm[0].claimed_interfaces) != expected:
            raise ValueError('Physical arm controller mapping is not active / complete')
        if not self.node.move_client.server_is_ready() or not self.execution.execute_client.server_is_ready():
            raise ValueError('Real MoveIt planning / execution action unavailable')
        return {'arm_controller': 'active', 'environment': 'real'}
