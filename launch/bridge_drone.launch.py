from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='drone_core',
            executable='drone_core_node',
            name='drone_core_node',
            output='screen',
        ),
        Node(
            package='vision_ai',
            executable='vision_ai_node',
            name='vision_ai_node',
            output='screen',
        ),
        Node(
            package='lidar_mapping',
            executable='lidar_mapping_node',
            name='lidar_mapping_node',
            output='screen',
        ),
        Node(
            package='web_dashboard',
            executable='web_dashboard_node',
            name='web_dashboard_node',
            output='screen',
        ),
    ])
