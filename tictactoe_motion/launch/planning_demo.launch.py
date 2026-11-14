from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    planner_node = Node(
        package='tictactoe_motion',
        executable='motion_planner',
        output='screen',
        parameters=[{
            'axis': 'x',
            'distance': 0.0,
            'velocity_scaling': 0.1,
            'acceleration_scaling': 0.1,
        }]
    )

    return LaunchDescription([planner_node])