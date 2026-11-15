"""Startup-only settings shared by motion planning, execution and recording."""

import math
from rcl_interfaces.msg import ParameterDescriptor


DEFAULTS = {
    'joint_states_topic': '/joint_states',
    'move_action_name': '/move_action',
    'execute_action_name': '/execute_trajectory',
    'stop_event_topic': '/trajectory_execution_event',
    'planning_group': 'arm',
    'planning_time': 5.0,
    'planning_attempts': 1,
    'position_tolerance': 0.0001,
    'orientation_tolerance': 0.01,
    'joint_goal_tolerance': 0.0001,
    'action_server_timeout': 5.0,
    'feedback_max_age': 1.0,
    'execution_start_tolerance': 0.01,
    'settle_timeout': 5.0,
    'stop_timeout': 5.0,
    'settle_period': 0.1,
    'settle_joint_tolerance': 0.0001,
    'settle_samples': 3,
    'recording_timeout': 5.0,
    'return_joint_tolerance': 0.001,
    'return_position_tolerance': 0.0003,
    'return_orientation_tolerance': 0.003,
    'state_log_period': 1.0,
}


def declare_settings(node):
    """! @brief Declare and validate immutable motion settings before wiring ROS interfaces."""
    values = {}
    for name, default in DEFAULTS.items():
        value = node.declare_parameter(
            name, default, ParameterDescriptor(read_only=True)
        ).value
        if isinstance(default, str):
            if not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        elif not math.isfinite(value) or (
            (value < 0) if name == 'state_log_period' else value <= 0
        ):
            raise ValueError(f"{name} must be finite and positive (state_log_period may be zero)")
        values[name] = value
    return values
