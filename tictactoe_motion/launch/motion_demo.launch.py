from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():
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
        axis_argument,
        distance_argument,
        velocity_scaling_argument,
        acceleration_scaling_argument,
        planner_node
    ])