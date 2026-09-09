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

## 오프라인 스캔 (촬영 → 나중에 SLAM)

실시간으로 SLAM을 돌리면 젯슨의 처리 속도가 카메라 입력을 못 따라가 프레임을
대량으로 버리고, 그 탓에 정합이 끊기면서 지도가 조각난다. 촬영 때는 원본만
녹화하고 나중에 느린 속도로 재생하면서 처리하면 프레임을 하나도 안 버린다.

```bash
# 1) 촬영 — 카메라만 띄우고 원본 프레임을 rosbag으로 녹화
./scripts/capture_bag.sh start 내스캔이름
#    ... 대상을 천천히, 끊김 없이 훑는다 ...
./scripts/capture_bag.sh stop

# 2) 재생하며 SLAM (0.25배속 권장 — 낮출수록 안전)
#    주의: 재생은 매번 -d 옵션으로 ~/.ros/rtabmap.db를 지우고 새로 만든다.
#    이전 스캔 결과를 보존하려면 재생 전에 반드시 백업할 것:
#      cp ~/.ros/rtabmap.db ~/.ros/rtabmap_<이름>.db
./scripts/replay_slam.sh ~/bags/내스캔이름 0.25

# 3) 3D 재구성 (포인트클라우드 + 텍스처 메쉬 + 궤적)
./scripts/reconstruct_from_flight.sh ~/.ros/rtabmap.db ~/.ros/내스캔이름_recon
```

재구성 품질 관련 실측 메모(2026-08-20):
- `--ba`(전역 번들 조정)를 붙이면 같은 표면이 여러 겹으로 어긋나 쌓이는
  고스팅이 줄어든다 — 벽 스캔에서 봉우리 2개(26mm 간격) → 1개, 두께 σ
  29.3mm → 20.7mm.
- `rtabmap-export`의 기본값은 `--decimation 4 --voxel 0.01`이라 원본 depth
  해상도를 거의 쓰지 않는다. 촘촘한 결과가 필요하면
  `--decimation 1 --voxel 0.004`(벽 스캔 기준 49만 → 711만 점).
- 점구름은 점마다 depth 노이즈(σ 약 20mm)만큼 흔들려서 아무리 촘촘히 해도
  사진처럼 선명해지지 않는다. 사진 같은 외관은 `--mesh --texture` 쪽이지만,
  **텍스처의 선명함은 형상의 정확도와 별개**임에 유의(균열 mm 측정은 후자에
  달려 있다).

같은 bag으로 파라미터만 바꿔 2번을 몇 번이고 다시 돌릴 수 있다 — 촬영을 다시
할 필요가 없다는 게 이 워크플로의 가장 큰 장점.

## 사진 기반 3D 재구성 (A안)

카메라 이동을 베이스라인으로 삼아 depth 카메라 단독보다 정확한 포즈를 얻고, 거기에
실제 크기(스케일)를 depth로 채워 넣는 경로. 배경은 `docs/bridge_drone_project_summary.md`
8번 항목 11 참고.

```bash
# 1) 촬영 — 기본 프로필이 1280x720x5 (해상도 우선, 데이터는 오히려 절반)
./scripts/capture_bag.sh start 내스캔이름
#    대상에서 90cm 떨어져, 몸을 좌우로 1m 움직이며 카메라는 대상을 계속 향하게.
#    10cm/s로 천천히, 높이를 20cm씩 바꿔 왕복, 마지막에 시작 지점으로 복귀. 60~90초.
#    ※ 한자리에서 카메라만 돌리면(패닝) baseline이 0이라 SfM이 실패한다.
./scripts/capture_bag.sh stop

# 2) 프레임 추출 (젯슨) — 다른 터미널에서 bag을 재생하며
python3 scripts/extract_frames.py --out ~/frames/내스캔 &
ros2 bag play ~/bags/내스캔이름 --rate 2

# 3) SfM으로 카메라 포즈 (Mac 등 colmap이 있는 곳, CUDA 불필요)
rsync -a homin@<젯슨IP>:~/frames/내스캔 ~/frames/
./scripts/sfm_poses.sh ~/frames/내스캔

# 4) depth 융합 — SfM의 미지 스케일을 depth로 확정하고 색을 입힘
./scripts/fuse_depth.py --poses ~/frames/내스캔/colmap/sparse/0/images.txt \
    --pose-format colmap --depth-dir ~/frames/내스캔/depth \
    --color-dir ~/frames/내스캔/images --intrinsics ~/frames/내스캔/intrinsics.json \
    --scale-from-sparse ~/frames/내스캔/colmap/sparse/0/points3D.txt \
    --out ~/frames/내스캔/cloud.ply

# 5) 브라우저에서 보고 거리 재기 (단일 HTML, 점 데이터 내장)
./scripts/make_viewer.py --cloud ~/frames/내스캔/cloud.ply \
    --poses ~/frames/내스캔/colmap/sparse/0/images.txt --scale <4단계가 출력한 스케일> \
    --title "내스캔" --out viewer.html

# 정합 품질 수치로 확인 (평면 두께)
./scripts/plane_sigma.py ~/frames/내스캔/cloud.ply
```

측정 정밀도: 점구름 노이즈가 σ≈21mm라 두 점 측정은 **±30mm** 수준이다.
10cm 미만은 신뢰하기 어렵고 1m 이상에서 가장 정확하다. **mm 단위 균열 측정은
이 3D가 아니라 2D+depth 경로**(`vision_ai`, 실측 오차 7%)에서 해야 한다.

## Test

순수 로직(하드웨어/ROS 실행 불필요)은 `pytest`로 바로 검증 가능:
```bash
pytest scripts/test/ src/lidar_mapping/test/   # cv2/numpy만 필요, Mac에서도 실행 가능
pytest src/vision_ai/test/                     # pyrealsense2 필요 — 젯슨에서만 실행 가능
```
