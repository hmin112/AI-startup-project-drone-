# Bridge Drone WS

AI 기반 교량 결함 측정 드론을 위한 ROS 2 Humble 워크스페이스입니다.

## 폴더 구조

```
bridge_drone_ws/
├── src/
│   ├── drone_core/       # MAVROS 통신, FC 제어 및 비행 상태 모니터링
│   ├── vision_ai/        # RealSense D455F 연동, YOLO 기반 실시간 균열 탐지 추론
│   ├── lidar_mapping/    # LiDAR SLAM, 센서 퓨전, 3D 포인트클라우드 맵 생성
│   └── web_dashboard/    # 분석 결과 및 3D 디지털 트윈 실시간 웹 시각화
├── launch/
│   └── bridge_drone.launch.py  # 4개 노드를 한번에 실행
├── models/                # 학습된 모델 가중치 (Git LFS 관리 예정)
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
