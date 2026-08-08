from launch import LaunchDescription
from launch_ros.actions import Node

# rgbd_odometry/rtabmap가 구독하는 카메라 토픽 (단일 캡처 지점인
# realsense2_camera_node가 발행, namespace='camera' name='camera'로
# 기동하면 /camera/camera/... 로 중첩됨 — 4.58.2 기준 실측 확인).
CAMERA_REMAPPINGS = [
    ('rgb/image', '/camera/camera/color/image_raw'),
    ('depth/image', '/camera/camera/aligned_depth_to_color/image_raw'),
    ('rgb/camera_info', '/camera/camera/color/camera_info'),
]


def generate_launch_description():
    return LaunchDescription([
        # D455F 단일 캡처 지점. vision_ai/SLAM 등 카메라가 필요한 모든 노드는
        # pyrealsense2로 디바이스를 직접 열지 않고 이 노드가 발행하는 토픽을
        # 구독한다 (카메라가 하나뿐이라 두 프로세스가 동시에 열면 충돌 위험).
        # 해상도는 기존 vision_ai의 수동 pyrealsense2 설정(depth 1280x720,
        # color 1280x800, 둘 다 30fps)과 맞춤 — 파라미터명이
        # depth_module.depth_profile / rgb_camera.color_profile 임에 주의
        # (구버전 realsense-ros의 *.profile과 다름, 4.58.2 기준 실측 확인).
        Node(
            package='realsense2_camera',
            executable='realsense2_camera_node',
            name='camera',
            namespace='camera',
            output='screen',
            parameters=[{
                'align_depth.enable': True,
                'enable_color': True,
                'enable_depth': True,
                'enable_infra1': False,
                'enable_infra2': False,
                'pointcloud.enable': False,
                'depth_module.depth_profile': '1280x720x30',
                'rgb_camera.color_profile': '1280x800x30',
            }],
        ),
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
            # 2026-08-07 DeepCrack 파인튜닝 결과(mask mAP50 0.194->0.403,
            # baseline 비교로 검증됨, docs/jetson_setup_log.md 참고). 워크스페이스
            # 루트(~/bridge_drone_ws)에서 실행한다고 가정한 상대경로 — README의
            # Run 안내와 동일한 전제.
            parameters=[{
                'model_path': 'models/crack_seg_v2_deepcrack_finetune.pt',
            }],
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
        # D455F의 드론 바디 기준 장착 위치. 실측 전까지의 대략값 —
        # 예전 base_link->laser(RPLIDAR)와 같은 자리(2026-08-07 하드웨어
        # 최종화로 LiDAR 제외, D455F가 그 역할까지 겸함).
        # camera_link 밑으로는(camera_link->camera_color_optical_frame 등)
        # realsense2_camera_node가 자체 발행하므로 base_link->camera_link만
        # 있으면 TF 체인이 완성된다(실측 확인 완료).
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_camera_tf',
            arguments=[
                '--x', '0', '--y', '0', '--z', '0.05',
                '--roll', '0', '--pitch', '0', '--yaw', '0',
                '--frame-id', 'base_link', '--child-frame-id', 'camera_link',
            ],
        ),
        # D455F 컬러+depth로 자체 Visual Odometry 계산, odom->base_link TF
        # 발행 + /odom 토픽 publish. drone_core/MAVROS에 의존하지 않는
        # 독립 오도메트리 소스로 설계함(Betaflight FC는 MAVROS와 정상
        # 통신하지 않을 가능성이 높아서 — 별도 이슈, docs 8번 항목 3 참고).
        Node(
            package='rtabmap_odom',
            executable='rgbd_odometry',
            name='rgbd_odometry',
            output='screen',
            parameters=[{
                'frame_id': 'base_link',
                'odom_frame_id': 'odom',
                'publish_tf': True,
                'approx_sync': True,
            }],
            remappings=CAMERA_REMAPPINGS,
        ),
        # 위 오도메트리 위에 루프클로징/맵빌딩을 얹어 map->odom 보정을
        # 발행하는 RTAB-Map 본체 (RPLIDAR 기반 slam_toolbox 대체).
        # '-d'는 기동 시마다 이전 세션 맵 DB를 지우고 새로 시작 — 지금은
        # 개발/검증 단계라 켜둠, 나중에 맵을 세션 간 유지해야 하면 제거.
        Node(
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[{
                'frame_id': 'base_link',
                'subscribe_depth': True,
                'approx_sync': True,
            }],
            remappings=CAMERA_REMAPPINGS + [('odom', '/odom')],
            arguments=['-d'],
        ),
        # vision_ai의 2D 탐지(카메라 프레임 3D 위치 포함)를 위 TF 체인으로
        # map 프레임까지 변환해서 /crack_fusion/tagged_detections로 재발행
        # (2D→3D 크랙 태깅, docs 8번 항목 2). odom/map이 아직 없으면(카메라
        # 정지 등으로 SLAM이 못 붙은 상태) 해당 탐지는 조용히 건너뜀.
        Node(
            package='lidar_mapping',
            executable='crack_fusion_node',
            name='crack_fusion_node',
            output='screen',
        ),
        # 원본 영상을 계속 보내는 대신 격자 칸 단위 스캔 완료 여부만 발행
        # (커버리지 그리드, docs 5번 항목). map/base_link TF가 없으면
        # 조용히 대기.
        Node(
            package='lidar_mapping',
            executable='coverage_grid_node',
            name='coverage_grid_node',
            output='screen',
        ),
    ])
