import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# 오프라인 재생 전용 SLAM 스택.
#
# scripts/capture_bag.sh로 녹화해둔 rosbag을 scripts/replay_slam.sh가 느린
# 속도로 재생하는 동안, 이 launch가 rgbd_odometry+rtabmap만 띄워서 지도를
# 만든다. 카메라/vision_ai/recorder/web_dashboard는 띄우지 않음 — 이미
# 녹화된 데이터를 처리하는 게 목적이고, 젯슨 CPU를 SLAM에 몰아주기 위함.
#
# 실시간 파이프라인은 launch/bridge_drone.launch.py 쪽이고, 이 파일과는
# 리맵/튜닝 설정을 공유해야 한다(아래 두 상수를 그쪽과 동일하게 유지할 것).

CAMERA_REMAPPINGS = [
    ('rgb/image', '/camera/camera/color/image_raw'),
    ('depth/image', '/camera/camera/aligned_depth_to_color/image_raw'),
    ('rgb/camera_info', '/camera/camera/color/camera_info'),
]

RTABMAP_TUNING_FILE = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'rtabmap_tuning.yaml'
)


def generate_launch_description():
    camera_extrinsic_args = [
        DeclareLaunchArgument('camera_x', default_value='0.0'),
        DeclareLaunchArgument('camera_y', default_value='0.0'),
        DeclareLaunchArgument('camera_z', default_value='0.05'),
        DeclareLaunchArgument('camera_roll', default_value='0.0'),
        DeclareLaunchArgument('camera_pitch', default_value='0.0'),
        DeclareLaunchArgument('camera_yaw', default_value='0.0'),
    ]

    # bag 재생 시각을 따라가야 하므로 모든 노드가 sim time을 써야 한다
    # (`ros2 bag play --clock`이 /clock을 발행). 이게 없으면 노드들이 벽시계를
    # 보면서 "메시지가 너무 오래됐다"고 판단해 전부 버린다.
    sim_time = {'use_sim_time': True}

    return LaunchDescription(camera_extrinsic_args + [
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_camera_tf',
            parameters=[sim_time],
            arguments=[
                '--x', LaunchConfiguration('camera_x'),
                '--y', LaunchConfiguration('camera_y'),
                '--z', LaunchConfiguration('camera_z'),
                '--roll', LaunchConfiguration('camera_roll'),
                '--pitch', LaunchConfiguration('camera_pitch'),
                '--yaw', LaunchConfiguration('camera_yaw'),
                '--frame-id', 'base_link', '--child-frame-id', 'camera_link',
            ],
        ),
        Node(
            package='rtabmap_odom',
            executable='rgbd_odometry',
            name='rgbd_odometry',
            output='screen',
            parameters=[
                {
                    'frame_id': 'base_link',
                    'odom_frame_id': 'odom',
                    'publish_tf': True,
                    'approx_sync': True,
                    # 재생 전용 핵심 설정: 기본값(true)은 밀린 프레임을 버리고
                    # 항상 최신 것만 처리한다 — 실시간엔 맞지만 재생 땐 애써
                    # 녹화한 프레임을 그대로 버리는 셈이라 끄고 전부 순서대로
                    # 처리하게 한다. 실시간 로그가 프레임을 버릴 때마다 직접
                    # 추천하던 파라미터이기도 함.
                    'always_process_most_recent_frame': False,
                },
                RTABMAP_TUNING_FILE,
                sim_time,
            ],
            remappings=CAMERA_REMAPPINGS,
        ),
        Node(
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[
                {
                    'frame_id': 'base_link',
                    'subscribe_depth': True,
                    'approx_sync': True,
                },
                RTABMAP_TUNING_FILE,
                sim_time,
            ],
            remappings=CAMERA_REMAPPINGS + [('odom', '/odom')],
            # 재생마다 이전 결과를 지우고 새 지도로 시작 — 같은 bag을 파라미터만
            # 바꿔 반복 재생하는 게 이 워크플로의 목적이라 항상 초기화한다.
            arguments=['-d'],
        ),
    ])
