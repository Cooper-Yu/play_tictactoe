"""Run all real-robot web GUIs and CPU perception inside The Construct."""
import sys
import os
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, GroupAction, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    share = Path(get_package_share_directory('tictactoe_gui'))
    return LaunchDescription([
        DeclareLaunchArgument('public_url', description='Exact output of webpage_address'),
        DeclareLaunchArgument('output_dir', default_value=str(
            Path.home()/'ros2_ws/src/play_tictactoe/data/cloud_gui')),
        DeclareLaunchArgument('grid_points', default_value=str(share/'config/grid_points_real.json')),
        DeclareLaunchArgument('cpu_threads', default_value='2'),
        SetEnvironmentVariable('PYTHONPATH', [
            str(Path.home()/'ros2_ws/src/play_tictactoe/.cloud-python'),
            os.pathsep, os.environ.get('PYTHONPATH', '')]),
        GroupAction([IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(share/'launch/localization_real.launch.py')),
            launch_arguments={'port':'8765', 'output_dir':str(
                Path.home()/'ros2_ws/src/play_tictactoe/data/localization_real')}.items())]),
        ExecuteProcess(cmd=[
            sys.executable, '-m', 'tictactoe_gui.real_game',
            '--workstation-url', 'http://127.0.0.1:8765/',
            '--weights', str(share/'models/xo_real.pt'),
            '--grid-points', LaunchConfiguration('grid_points'),
            '--device', 'cpu', '--cpu-threads', LaunchConfiguration('cpu_threads'),
            '--port', '8775', '--output', LaunchConfiguration('output_dir')],
            output='screen'),
        ExecuteProcess(cmd=[
            sys.executable, '-m', 'tictactoe_gui.cloud_gateway',
            '--public-url', LaunchConfiguration('public_url'),
            '--port', '7000', '--upstream-port', '8765', '--game-port', '8775'],
            output='screen'),
    ])