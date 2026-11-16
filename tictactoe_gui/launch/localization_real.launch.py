"""Explicit real Piper workstation; startup never enables or moves the arm."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def start(context):
    output = str(Path(LaunchConfiguration('output_dir').perform(context)).expanduser())
    port = int(LaunchConfiguration('port').perform(context))
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid port')
    config = Path(get_package_share_directory('tictactoe_motion'))/'config'
    arguments = ['--environment', 'real', '--port', str(port), '--output', output]
    return [Node(package='tictactoe_gui', executable='localization_gui', output='screen',
                 arguments=arguments,
                 parameters=[str(config/'common.yaml'), str(config/'real.yaml'),
                             {'poses_file':str(Path(output)/'poses_real.json'), 'state_log_period':0.,
                              'velocity_scaling':.05, 'acceleration_scaling':.05}])]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('port', default_value='8765'),
        DeclareLaunchArgument('output_dir', default_value='~/ros2_ws/src/play_tictactoe/data/localization_real'),
        OpaqueFunction(function=start)])
