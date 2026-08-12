# Bridge Drone WS

AI 기반 교량 결함 측정 드론을 위한 ROS 2 Humble 워크스페이스입니다.

## 폴더 구조

```
bridge_drone_ws/
├── src/
│   ├── drone_core/       # MAVROS 통신, FC 제어 및 비행 상태 모니터링
│   ├── vision_ai/        # RealSense D455F 연동, YOLO 기반 실시간 균열 탐지 추론
│   ├── lidar_mapping/    # D455F 기반 Visual SLAM(RTAB-Map) 상태 요약 — 실제 오도메트리/맵빌딩은 rtabmap_odom/rtabmap_slam(launch에서 직접 기동), 이 패키지는 /info 구독해서 /lidar_mapping/status만 발행
│   └── web_dashboard/    # 분석 결과 및 3D 디지털 트윈 실시간 웹 시각화
├── launch/
│   └── bridge_drone.launch.py  # D455F 캡처(realsense2_camera) + drone_core/vision_ai/lidar_mapping/web_dashboard + RTAB-Map(rgbd_odometry, rtabmap) 전체 기동
├── models/                # 학습된 모델 가중치(Git LFS) + training_records/(에포크별 학습 기록)
├── scripts/               # 데이터셋 변환 등 1회성 도구 스크립트
└── docs/                  # 문서
```

## Build

```bash
cd ~/bridge_drone_ws
colcon build --symlink-install
source install/setup.bash
```

## Run

```bash
ros2 launch launch/bridge_drone.launch.py
```

카메라 장착 위치가 실측되면 코드를 안 고치고 커맨드라인에서 바로 반영 가능:
```bash
ros2 launch launch/bridge_drone.launch.py camera_z:=0.08 camera_pitch:=0.15
```

## Test

순수 로직(하드웨어/ROS 실행 불필요)은 `pytest`로 바로 검증 가능:
```bash
pytest scripts/test/ src/lidar_mapping/test/   # cv2/numpy만 필요, Mac에서도 실행 가능
pytest src/vision_ai/test/                     # pyrealsense2 필요 — 젯슨에서만 실행 가능
```
