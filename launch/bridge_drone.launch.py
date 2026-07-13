import os

from launch import LaunchDescription
from launch_ros.actions import Node

SLAM_PARAMS_FILE = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'mapper_params_online_async.yaml'
)


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
        # RPLIDAR A3의 드론 바디 기준 장착 위치. 실측 전까지의 대략값이며
        # 실제 장착 후 캘리브레이션해서 갱신해야 한다 (D455F가 그랬듯
        # 처음엔 공장/추정값으로 시작해도 무방).
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_laser_tf',
            arguments=[
                '--x', '0', '--y', '0', '--z', '0.1',
                '--roll', '0', '--pitch', '0', '--yaw', '0',
                '--frame-id', 'base_link', '--child-frame-id', 'laser',
            ],
        ),
        # 라이다 스캔매칭 기반 SLAM. drone_core가 발행하는 odom->base_link
        # 위에 map->odom 보정을 얹는 표준 nav2/slam_toolbox 구성 (GPS 없이도
        # 동작 — 교량 하부 GPS 음영구역 대응).
        Node(
            package='slam_toolbox',
            executable='async_slam_toolbox_node',
            name='slam_toolbox',
            output='screen',
            parameters=[SLAM_PARAMS_FILE],
        ),
    ])
