"""Launch the local-only tablet against an already-running simulation."""
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
        raise ValueError('Port must be in 1024..65535')
    config = Path(get_package_share_directory('tictactoe_motion'))/'config'
    return [Node(package='tictactoe_gui', executable='canvas_gui', output='screen',
                 arguments=['--port', str(port), '--output', output],
                 parameters=[str(config/'common.yaml'), str(config/'sim.yaml'),
                             str(config/'board_demo_sim.yaml'),
                             {'poses_file':str(Path(output)/'poses_sim.json'),
                              'state_log_period':0.0, 'cartesian_step':.0003}])]


def generate_launch_description():
    """! @brief Start a simulation-only canvas; startup never executes a motion."""
    return LaunchDescription([
        DeclareLaunchArgument('port', default_value='8765'),
        DeclareLaunchArgument('output_dir', default_value='~/.local/share/play_tictactoe/canvas_sim'),
        OpaqueFunction(function=start)])
