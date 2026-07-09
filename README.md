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
├── docker/
│   ├── Dockerfile.jetson  # Jetson(JetPack 6 / L4T R36) 배포용 이미지
│   └── entrypoint.sh
├── models/                # 학습된 모델 가중치 (Git LFS 관리 예정)
└── docs/                  # 문서
```

## Build (로컬 / 개발)

```bash
cd ~/bridge_drone_ws
colcon build --symlink-install
source install/setup.bash
```

## Run

```bash
ros2 launch launch/bridge_drone.launch.py
```

## Jetson 배포 (JetPack 6, Docker)

Jetson 보드에 JetPack 6가 설치되어 있고 nvidia-container-runtime이 활성화되어 있어야 합니다.

1. Jetson에 설치된 정확한 L4T 버전 확인:

   ```bash
   cat /etc/nv_tegra_release
   ```

2. 해당 버전에 맞는 베이스 이미지 태그로 빌드 (기본값은 JetPack 6.0 / L4T R36.3.0):

   ```bash
   cd ~/bridge_drone_ws
   docker build -f docker/Dockerfile.jetson \
     --build-arg BASE_IMAGE=dustynv/ros:humble-desktop-l4t-r36.3.0 \
     -t bridge_drone:jetson .
   ```

3. 실행 (GPU / TensorRT 사용을 위해 `--runtime nvidia` 필요):

   ```bash
   docker run -it --rm \
     --runtime nvidia \
     --network host \
     --device /dev/ttyUSB0 \
     bridge_drone:jetson
   ```

베이스 이미지 태그 목록은 https://hub.docker.com/r/dustynv/ros/tags 에서 확인할 수 있습니다.
