# Jetson 개발 환경 세팅 기록 (2026-07-09)

팀 전컴토 — AI 교량 결함 측정 드론 프로젝트. 프로젝트 개요는 `bridge_drone_project_summary.md` 참고.

## 접속 정보

```
ssh homin@100.79.110.90
```
- 비밀번호: `0000` (계정 로그인, sudo 동일)
- 호스트명: `homin-desktop`
- Tailscale로 연결됨 (100.79.110.90은 tailscale0 IP)

## 오늘 한 일

1. **맥 → Jetson 파일 이전**
   - `~/bridge_drone_ws` 폴더 구조 생성 (`src/{drone_core,vision_ai,lidar_mapping,web_dashboard}`, `launch/`, `models/`, `docs/`)
   - `bridge_drone_project_summary.md` → `~/bridge_drone_ws/docs/`로 복사
   - 이전 세션의 `.claude/settings.local.json`(권한 allowlist) → `~/bridge_drone_ws/.claude/`로 복사

2. **Jetson 환경 확인**
   - JetPack 6 (L4T R36.4.3), Ubuntu 22.04.5 LTS
   - CUDA 12.6, cuDNN 9.3, TensorRT 10.3 — 전부 이미 설치돼 있었음 (PATH만 안 잡혀있었음)
   - Docker 27.5.0 설치돼 있음
   - 센서(RealSense D455F, RPLIDAR A3, FC)는 이 시점 기준 물리적으로 연결 안 된 상태 (`lsusb`에 Logitech 동글/블루투스만 있음)

3. **소프트웨어 설치**
   - `python3-pip` 설치
   - **ROS 2 Humble** 설치 (`ros-humble-ros-base` + `ros-dev-tools`) — `colcon` 포함
   - `/opt/ros/humble/setup.bash`, `/usr/local/cuda-12.6/bin` 을 `~/.bashrc`에 자동 소싱하도록 추가함 → 새 쉘 열면 자동으로 `ros2`, `nvcc` 커맨드 사용 가능

4. **네트워크 이슈 발견 및 해결**
   - apt 설치 중 `Clearsigned file isn't valid, got 'NOSPLIT'`, `Hash Sum mismatch` 에러가 랜덤하게 발생
   - 원인: **조선대 캠퍼스 네트워크의 콘텐츠 필터링 장비**가 일부 HTTP(비암호화) 다운로드를 간헐적으로 가로채서 차단 페이지(`ip.chosun.ac.kr/block.bih?...`)로 바꿔치기함
   - 해결: `/etc/apt/sources.list`의 `ports.ubuntu.com`을 `http://` → `https://`로 변경. `packages.ros.org`는 HTTPS 인증서가 안 맞아서 그냥 재시도(3~5회)로 우회함
   - **다음에 또 이런 apt/네트워크 에러가 나오면 이 필터부터 의심할 것**

5. **빌드 테스트**
   - `~/bridge_drone_ws/src/drone_core/`에 최소 동작하는 ROS2 파이썬 패키지 스켈레톤 생성 (`package.xml`, `setup.py`, `setup.cfg`, `drone_core_node.py`)
   - `colcon build --symlink-install` 성공
   - `ros2 run drone_core drone_core_node` 실행 → 정상 기동 로그 확인 (`drone_core_node started`)
   - 처음에 `setup.cfg` 없이 빌드했더니 콘솔 스크립트가 `install/drone_core/bin/`에 잘못 설치돼서 `ros2 run`이 못 찾는 문제가 있었음 → `setup.cfg`에 `script_dir`/`install_scripts`를 `$base/lib/drone_core`로 지정해서 해결

6. **D455F 카메라 연결 및 SDK 설치 (2026-07-09 저녁, 드론/라이다는 아직 없어서 카메라만 우선 테스트)**
   - USB로 연결된 D455F가 `lsusb`/`/dev/video*`에 정상 인식되는 건 먼저 확인 (표준 UVC 드라이버로 잡힘)
   - ffmpeg로 raw 프레임 캡처해서 RGB는 정상, depth는 실제 값인지 확인 안 됨(밝기 보정 없이 봐서 새까맣게 나옴) → 정식 SDK 필요하다고 판단
   - **librealsense를 소스에서 빌드** (Jetson/ARM이라 apt 패키지 없음, JetsonHacks 방식 참고)
     - `git clone --depth 1 https://github.com/IntelRealSense/librealsense.git ~/librealsense`
     - `./scripts/setup_udev_rules.sh` 실행 — 카메라가 이미 꽂혀 있으면 내부에서 `read -p`로 대기하니, 자동화할 땐 stdin에 개행을 하나 더 흘려줘야 함 (`printf "비번\n\n" | sudo -S ...`)
     - cmake 옵션: `-DFORCE_RSUSB_BACKEND=true`(커널 패치 불필요) `-DBUILD_PYTHON_BINDINGS=true` `-DBUILD_EXAMPLES=false -DBUILD_GRAPHICAL_EXAMPLES=false`(GUI 예제 뷰어는 제외 — 아래 이유 때문)
     - 빌드 중 두 번 실패했었음: ① `GL/glu.h` 헤더 없음 → `libglu1-mesa-dev` 설치로 해결, ② 그래도 `gluPerspective`/`gluLookAt` 링크 에러 남 → 그냥 GUI 예제(`BUILD_EXAMPLES`/`BUILD_GRAPHICAL_EXAMPLES`)를 꺼서 우회 (우리한텐 필요없는 3D 뷰어였음)
     - `sudo make install` 완료, `pyrealsense2` 파이썬 모듈도 함께 설치됨
   - **검증**: `rs-enumerate-devices --short` → `Intel RealSense D455F` 정상 인식 (펌웨어 5.15.1.55)
   - **depth 실측 테스트** (`~/depth_test.py`, pyrealsense2로 depth+color 스트림 열어서 실제 미터 단위 거리 계산): depth scale 0.001m/unit, 유효 픽셀 46248/101760, 최소 0.165m~최대 7.622m, 평균 1.858m — **실내 공간 스캔 값으로 정상**. colorize한 depth 이미지도 육안으로 거리별 색 구분이 명확하게 보임 → **depth 파이프라인 정상 작동 확인**
   - 컬러 프레임은 이번 캡처에서 캄캄하게 나왔는데, 이건 자동노출 워밍업 프레임 부족/조명 문제로 보이고 depth SDK와는 무관함

7. **카메라 캘리브레이션 (intrinsic 추출)**
   - D455F는 출고 시 공장 캘리브레이션 값을 자체 저장하고 있어서, 체스보드 없이 `pyrealsense2`로 바로 추출 가능
   - 1280x720(depth) / 1280x800(color) 최대 해상도 기준으로 fx, fy, ppx, ppy, distortion coeffs, depth-to-color extrinsics, depth_scale(0.001 m/unit) 전부 추출 완료
   - 저장 위치: `~/bridge_drone_ws/models/camera_calibration/d455f_intrinsics_1280x720.json` (+ 추출 스크립트 `get_intrinsics.py`)
   - 이 값으로 "픽셀 거리 → 실제 mm" 환산 공식 사용 가능: `실제mm = (픽셀길이 / fx) × 거리(m) × 1000`
   - 참고: 지금은 공장 캘리브레이션 값이라 충분하지만, 정밀도가 중요해지면 체스보드로 재보정/검증 권장

8. **PyTorch + YOLO GPU 추론 테스트**
   - JetPack 6.1 (L4T R36.4.3) + CUDA 12.6용 PyTorch는 일반 pip로 안 되고 전용 wheel 필요:
     - cuSPARSELt 먼저 설치 (`pytorch/pytorch` 레포의 `install_cusparselt.sh`, `CUDA_VERSION=12.4`로 지정 — 정규식이 12.1~12.4만 매칭해서 12.6을 그대로 쓰면 안 됨)
     - NVIDIA 공식 wheel(`developer.download.nvidia.com/compute/redist/jp/v61/pytorch/...`)로 torch 2.5.0 설치 성공, GPU(`Orin`) 인식 확인
     - 근데 이 조합엔 맞는 torchvision이 없어서, 결국 **Jetson AI Lab pip 인덱스**(`https://pypi.jetson-ai-lab.io/jp6/cu126` — `.io`가 맞는 도메인, `.dev`는 DNS도 안 뜸)에서 `torch==2.8.0` + `torchvision==0.23.0` 짝 맞춰서 재설치함. 처음부터 이 인덱스로 했으면 더 빨랐을 것
     - `ultralytics`(YOLO)는 `--no-deps`로 설치해서 torch/torchvision을 안 건드리게 함
   - **테스트 결과**: D455F로 캡처한 실제 프레임에 `yolov8n` 사전학습 모델로 추론 → GPU에서 **평균 36.5ms/프레임 (27.4 FPS)** — 드론 실시간 스캔에 충분한 속도
   - 이번 테스트 프레임은 방 불을 꺼놓은 상태라 완전히 캄캄하게 나와서 탐지 결과는 0개였음 — **소프트웨어 문제 아니고 촬영 환경 문제**. 파이프라인 자체(설치, GPU 인식, 속도)는 검증 완료

9. **픽셀→mm 변환 유틸리티 작성 및 검증**
   - `~/bridge_drone_ws/models/camera_calibration/pixel_to_mm.py`에 핵심 함수 `measure_distance_mm(depth_frame, intrinsics, point_a, point_b)` 작성
   - 단순히 "같은 깊이"라고 가정하는 근사식이 아니라, `rs.rs2_deproject_pixel_to_point`로 두 점을 각각 실제 3D 좌표로 변환한 뒤 유클리드 거리를 구하는 **정확한 방식**으로 구현 (균열 양 끝점이 기울어진 면 위에서 서로 다른 깊이일 수 있기 때문)
   - 검증: 실제 카메라로 "같은 표면 위의 가까운 두 점"(80px 간격, 깊이 1.34m/1.40m로 유사)을 테스트 → 정확한 3D 계산 137.3mm vs 단순 근사식 164.8mm, **차이 20%** → 표면이 카메라 기준 살짝 기울어져 있어서 단순식은 부정확하고 3D 계산이 필요하다는 게 실측으로 확인됨
   - 서로 다른 물체(먼 배경 등)를 잘못 짚으면 두 방식 차이가 60~70%까지도 벌어짐을 확인 — 실제 균열 탐지 결과(YOLO/세그멘테이션의 두 끝점)를 넣을 때도 반드시 이 3D 방식을 써야 함
   - 나중에 실제 균열 크기 계산 로직은 이 함수를 그대로 재사용하면 됨 (`vision_ai` 노드에서 YOLO가 크랙 바운딩박스/윤곽선의 두 끝점 픽셀좌표를 뽑아서 이 함수에 넣으면 mm 길이가 나옴)

## 현재 상태 요약

| 항목 | 상태 |
|---|---|
| 폴더 구조 | ✅ 완료 |
| CUDA / cuDNN / TensorRT | ✅ 정상 (JetPack 기본 포함) |
| Docker | ✅ 정상 |
| ROS 2 Humble + colcon | ✅ 설치 및 빌드 테스트 완료 |
| D455F 카메라 | ✅ 연결됨, librealsense SDK 빌드 완료, depth/color 스트림 실측 검증 완료 |
| 카메라 캘리브레이션(intrinsic) | ✅ 완료 (공장값 추출, mm 환산 공식 확보) |
| PyTorch + torchvision + YOLO | ✅ 설치 완료, GPU 추론 27.4 FPS 확인 |
| 픽셀→mm 변환 유틸 | ✅ 작성 및 실측 검증 완료 (`pixel_to_mm.py`) |
| RPLIDAR A3, FC | ❌ 아직 없음 (드론 자체가 아직 없음) |
| `drone_core` 실제 로직 (MAVROS 등) | ❌ 스켈레톤만 있음, 실제 구현 필요 |
| `vision_ai`, `lidar_mapping`, `web_dashboard` | ❌ 폴더만 있고 내용 없음 |

## 2026-07-12 후속 테스트

- [x] **불 켜고 YOLO 재테스트** — `~/yolo_test.py` 그대로 재실행 (워밍업 30프레임은 이미 반영돼 있었음). 결과: 컬러 프레임 정상 밝기로 캡처됨, YOLO가 책상 위 키보드를 `keyboard 0.78` 신뢰도로 정확히 탐지 (결과 이미지 `/tmp/yolo_result.jpg`). 추론 속도 평균 39.4ms/frame (25.4 FPS) — GPU 가속 정상, 7/9 테스트(27.4 FPS)와 비슷한 수준. 지난번 캄캄하게 나온 건 촬영 환경(불 꺼짐) 문제였을 뿐이고, D455F 컬러 스트림·YOLO 파이프라인 자체는 이상 없음을 확인.

## 2026-07-12 `vision_ai` ROS2 노드 구현

- `~/depth_test.py`, `~/yolo_test.py`, `models/camera_calibration/pixel_to_mm.py` 세 단독 스크립트를 실제 `vision_ai` ROS2 패키지로 통합 (`src/vision_ai/vision_ai/vision_ai_node.py`, `measurement.py`)
- 구조: 백그라운드 스레드에서 RealSense 캡처(depth 1280x720 + color 1280x800, `rs.align`으로 color에 정렬) + YOLO 추론을 계속 돌리고, ROS2 타이머(10Hz)는 락으로 보호된 최신 결과만 읽어서 publish — Core Rule의 "메인 스레드 블로킹 금지" 준수
- 토픽: `/vision_ai/detections` (`std_msgs/String`, JSON — class/confidence/bbox/width_mm/height_mm), `/vision_ai/annotated` (`sensor_msgs/Image`, `qos_profile_sensor_data`)
- bbox 양 끝점을 `pixel_to_mm.py`의 `measure_distance_mm()`(그대로 이식, 로직 변경 없음)에 넣어서 mm 크기까지 계산. depth 무효(0)면 크래시 대신 `null` 처리
- 모델 경로는 ROS2 파라미터(`model_path`, 기본 `yolov8n.pt`)로 — 나중에 균열 전용 모델로 교체 시 코드 수정 불필요
- 사전 설치: `ros-humble-cv-bridge` (미설치 상태였음)
- **버그 발견 및 수정**: SIGINT로 노드 종료 시 `rclpy.shutdown()`이 이미 내부적으로 호출된 뒤 또 호출돼서 `RCLError: rcl_shutdown already called` 트레이스백 발생 → `if rclpy.ok(): rclpy.shutdown()`으로 가드 추가, 재검증 완료 (트레이스백 없이 깨끗하게 종료)
- **검증 결과**: `colcon build` 성공, 노드 기동 후 `/vision_ai/annotated` ~9.4Hz로 안정적 publish, `/vision_ai/detections`에서 키보드 탐지(`confidence` 0.83~0.86) JSON 정상 수신. 단, 이번 테스트에서는 카메라와 물체(키보드)가 너무 가까워서(D455F 최소 감지거리 이내로 추정 — depth 진단 스크립트로 bbox 중심·이미지 중심 모두 depth=0 확인) `width_mm`/`height_mm`는 계속 `null`로 나옴. **코드 버그 아니고 촬영 거리 문제** — mm 계산 로직 자체는 7/9에 이미 실측 검증됨(137.3mm vs 164.8mm 근사식 비교)
- 코드는 GitHub(`hmin112/AI-startup-project-drone-`)에 커밋/푸시로 관리 시작 (그동안 로컬에만 있던 7/9~7/12 작업분도 이번에 처음 반영)

## Git / GitHub 관리 방식 (2026-07-12부터)

- 앞으로 작업은 GitHub `hmin112/AI-startup-project-drone-` (main 브랜치)에 꾸준히 커밋/푸시하며 관리. 레포 루트 = `bridge_drone_ws/` 내용물 그대로 (README.md, .gitignore, docs/, launch/, models/, src/).
- **커밋/푸시는 Jetson이 아니라 맥에서 진행.** Jetson은 학교 공용 장비라 GitHub 인증(계정/토큰/SSH 키)을 일부러 넣어두지 않음. 맥 로컬 클론 경로: `~/Desktop/조선대학교/공모전/신기술 SW창업프로젝트/bridge_drone_ws` (`gh` CLI로 `hmin112` 계정 인증 완료된 상태).
- 작업 흐름: 맥 클론에서 파일 작성/수정 → 해당 파일만 `scp`로 Jetson `~/bridge_drone_ws/`에 올려서 `colcon build`/실행으로 검증 → 맥 클론에서 `git add`/`commit`/`push`.
- `bridge_drone_ws/.claude/settings.local.json`(Jetson에만 있는 권한 allowlist)은 `.gitignore`에 추가해서 의도적으로 커밋 대상에서 제외.
- **한 번 발견된 함정**: 이번에 처음 동기화하면서 보니 GitHub와 Jetson이 서로 반대 방향으로 밀려 있었음 — GitHub엔 `drone_core`/`lidar_mapping`/`web_dashboard`가 더 발전된 스켈레톤으로 있었는데 Jetson엔 반영 안 돼 있었고(특히 lidar_mapping/web_dashboard는 Jetson에 빈 폴더뿐), 반대로 Jetson의 카메라 캘리브레이션/`pixel_to_mm.py`/문서 최신본은 GitHub에 없었음. **앞으로 두 방향 중 하나로 무작정 덮어쓰지 말고, 매번 `git status`/diff로 양쪽 다 확인하고 동기화할 것.**

## 2026-07-12 균열 데이터셋 조사

목표: 탐지(detection) + mm 측정(measurement) 둘 다 하려면 어떤 공개 데이터셋을 쓸지 조사.

**1. 바로 쓰기 좋은 것 — Ultralytics 공식 통합 세그멘테이션 데이터셋**
- [Crack Segmentation Dataset (Ultralytics Docs)](https://docs.ultralytics.com/datasets/segment/crack-seg) — 4,029장, train/val/test 분리 완료, `ultralytics` 라이브러리에 이미 내장돼서 `data=crack-seg.yaml`만 지정하면 바로 학습 가능
- 세그멘테이션(마스크) 포맷이라 바운딩박스보다 균열의 실제 윤곽을 잡기 좋음 — "측정"이 목표인 이 프로젝트엔 바운딩박스보다 유리 (마스크 윤곽선 두 끝점을 그대로 `vision_ai/measurement.py`의 `measure_distance_mm()`에 넣을 수 있음)

**2. 학술 표준 데이터셋 (더 크고 다양함)**
- [SDNET2018](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6247444/) — 56,000장+, 콘크리트 교량 바닥판/벽/포장, 균열 폭 0.06~25mm. **주의: 이건 바운딩박스/세그멘테이션이 아니라 256x256 패치 단위 "균열 있음/없음" 분류(classification) 데이터셋** — YOLO 탐지/세그멘테이션 학습에 그대로 섞어 쓸 수 없고, 별도 재라벨링하거나 사전학습(pretraining)/2차 필터링 용도로만 활용 가능
- [DeepCrack](https://github.com/HqiTao/CT-crackseg) — 537장, 픽셀 단위 세그멘테이션 라벨 (정밀 측정용으로 적합, 다만 수량이 적음)
- Crack500 / CrackTree206 / CFD — 도로 포장 균열 위주, 세그멘테이션 마스크 제공 (교량이 아니라 도로라 도메인이 약간 다름)

**3. 드론 촬영 특화 (구조상 가장 유사한 케이스)**
- [Crack-detection-public-dataset-collection (GitHub, 14개 정리)](https://github.com/Arthasyue/Crack-detection-public-dataset-collection) 중 **UAV-pdd2023**(드론 촬영 도로 결함), **HighRPD**(고고도 드론 포장 결함), **BCD**(교량 균열 전용) — 핸드헬드가 아니라 드론 시점이라 실제 D455F가 찍을 각도/거리와 유사. 다만 데이터 수가 상대적으로 적을 수 있음

**4. Roboflow (바로 YOLO bbox 포맷)**
- [Bridge crack (project-coxus)](https://universe.roboflow.com/project-coxus/bridge-crack-vczr8/dataset/1), [concrete surface crack (vijayalakshmi, 1,299장)](https://universe.roboflow.com/vijayalakshmi-2yshx/concrete-surface-crack-detection-using-yolov5-model/dataset/3) 등 — TXT+YAML로 바로 학습 가능, 다만 개별 규모가 작음(수백~수천 장)

**결정 보류 — 다음에 정할 것**: 1번(crack-seg)으로 파이프라인부터 빠르게 검증 → 이후 3번(드론 앵글, BCD/UAV-pdd2023)으로 확장하는 순서 추천. 2번의 SDNET2018은 포맷이 달라(분류 전용) 바로 섞이지 않으니 별도 취급 필요.

## 다음에 이어서 할 것

- [ ] 카메라를 실제 스캔 거리(수십 cm~수 m)에서 재테스트해서 `width_mm`/`height_mm`가 정상적으로 채워지는지 확인 — **보류 중 (2026-07-12 기준)**: 지금 집이라 Jetson/카메라가 학교에 있어서 물리적으로 카메라 위치를 옮길 수 없음. 학교 가서 재시도.
- [ ] 균열 탐지 전용 YOLO 모델 학습 (데이터셋 후보는 위 조사 완료 — crack-seg로 시작 → BCD/UAV-pdd2023로 확장 여부 결정 필요, 문서 8번 항목 5번)
- [ ] 드론/라이다 준비되면: RPLIDAR A3, FC 연결 테스트 → `drone_core`(MAVROS), `lidar_mapping` 진행
- [ ] `web_dashboard` 스켈레톤 만들기
- [ ] 프로젝트 요약 문서(8번 항목)의 남은 미해결 설계 이슈들 — 2D-3D 태깅, GPS 음영구역 EKF, 센서 캘리브레이션(멀티센서 간) 등
