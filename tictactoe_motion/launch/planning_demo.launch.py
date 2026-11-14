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

    planner_node = Node(
        package='tictactoe_motion',
        executable='motion_planner',
        output='screen',
        parameters=[{
            'axis': LaunchConfiguration('axis'),
            'distance': ParameterValue(
                LaunchConfiguration('distance'),
                value_type=float
            ),
            'velocity_scaling': 0.1,
            'acceleration_scaling': 0.1,
        }]
    )

    return LaunchDescription([axis_argument, distance_argument, planner_node])