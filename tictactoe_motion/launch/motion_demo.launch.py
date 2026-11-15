from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue
from pathlib import Path

def generate_launch_description():
    recording_arguments = [
        DeclareLaunchArgument('environment', default_value='sim',
                              description='Pose record environment: sim or real'),
        DeclareLaunchArgument(
            'poses_file',
            default_value=[str(Path.home() / 'ros2_ws/src/play_tictactoe/data/poses_'),
                           LaunchConfiguration('environment'), '.json'],
            description='Writable persistent pose JSON file'),
        DeclareLaunchArgument('record_name', default_value='A'),
        DeclareLaunchArgument('overwrite', default_value='false'),
    ]
    axis_argument = DeclareLaunchArgument(
        'axis',
        default_value='x',
        description='Movement axis in base_link: x, y, or z'
    )

    distance_argument = DeclareLaunchArgument(
        'distance',
        default_value='0.0',
        description='Signed movement distance in meters'
    )

    velocity_scaling_argument = DeclareLaunchArgument(
        'velocity_scaling',
        default_value='0.1',
        description='Joint velocity scaling factor in (0, 1]'
    )

    acceleration_scaling_argument = DeclareLaunchArgument(
        'acceleration_scaling',
        default_value='0.1',
        description='Joint acceleration scaling factor in (0, 1]'
    )

    planner_node = Node(
        package='tictactoe_motion',
        executable='motion_demo',
        output='screen',
        parameters=[{
            'environment': ParameterValue(LaunchConfiguration('environment'), value_type=str),
            'poses_file': ParameterValue(LaunchConfiguration('poses_file'), value_type=str),
            'record_name': ParameterValue(LaunchConfiguration('record_name'), value_type=str),
            'overwrite': ParameterValue(LaunchConfiguration('overwrite'), value_type=bool),
            'axis': LaunchConfiguration('axis'),
            'distance': ParameterValue(
                LaunchConfiguration('distance'),
                value_type=float
            ),
            'velocity_scaling': ParameterValue(
                LaunchConfiguration('velocity_scaling'),
                value_type=float
            ),
            'acceleration_scaling': ParameterValue(
                LaunchConfiguration('acceleration_scaling'),
                value_type=float
            ),
        }]
    )

    return LaunchDescription([
        *recording_arguments,
        axis_argument,
        distance_argument,
        velocity_scaling_argument,
        acceleration_scaling_argument,
        planner_node
    ])
