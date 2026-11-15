"""Load shared settings, the selected environment and explicit launch overrides."""

from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _start_node(context):
    environment = LaunchConfiguration('environment').perform(context)
    if environment not in ('sim', 'real'):
        raise ValueError('environment must be sim or real')
    config = Path(get_package_share_directory('tictactoe_perception')) / 'config'
    overrides = {'environment': environment}
    for name, value_type in OVERRIDES.items():
        value = LaunchConfiguration(name).perform(context)
        if value:
            overrides[name] = ParameterValue(LaunchConfiguration(name), value_type=value_type)
    return [Node(
        package='tictactoe_perception', executable='enhancement_demo', output='screen',
        parameters=[str(config / 'common.yaml'), str(config / f'{environment}.yaml'), overrides],
    )]


OVERRIDES = {'camera_topic': str, 'initial_brightness_beta': int, 'window_name': str, 'log_images': bool}


def generate_launch_description():
    """! @brief Start the demo with real defaults; startup never commands robot motion."""
    return LaunchDescription([
        DeclareLaunchArgument('environment', default_value='real', choices=['sim', 'real']),
        *[DeclareLaunchArgument(name, default_value='',
                               description='Optional override of the selected YAML value')
          for name in OVERRIDES],
        OpaqueFunction(function=_start_node),
    ])
