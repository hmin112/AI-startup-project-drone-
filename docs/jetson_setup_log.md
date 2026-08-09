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

## 2026-07-12 균열 세그멘테이션 모델 학습 시도 (진행 중 문제 발생, 중단)

목표: crack-seg 데이터셋으로 `yolov8n-seg` 100에포크 학습 → 추론 검증 → `vision_ai_node`를 세그멘테이션 기반 mm 측정으로 업그레이드.

**코드 작업은 완료:**
- `src/vision_ai/vision_ai/vision_ai_node.py`의 측정 로직을 bbox 축정렬 방식에서 **마스크 기반**으로 교체함. `result.masks.xy`(디텍션별 마스크 폴리곤)를 `cv2.minAreaRect()`에 넣어 균열 방향에 맞는 회전 사각형을 구하고, `cv2.boxPoints()`로 얻은 인접 두 변을 각각 `measurement.measure_distance_mm()`으로 mm 환산 → 더 긴 변을 `length_mm`, 짧은 변을 `width_mm`으로 JSON에 담음 (필드명이 `width_mm`/`height_mm`에서 `length_mm`/`width_mm`로 바뀜, 아직 소비자 없어서 하위호환 문제 없음). 마스크가 없는 모델(순수 detection)로 되돌릴 경우를 위해 기존 bbox 축정렬 방식 폴백도 유지. `colcon build` 성공까지 확인함.
- 이 코드는 라이브 카메라로 직접 스모크테스트는 아직 못 했음 (아래 인시던트 때문에 미룸 — GPU/메모리를 학습이 다 쓰고 있어서 동시 실행 피함).

**학습 시도 중 겪은 문제들 (시간순):**
1. `yolo` CLI가 비대화형 SSH 세션 PATH에 없어서 처음 실행 실패 (`~/.local/bin`이 PATH에 없음) → `export PATH=$HOME/.local/bin:$PATH`로 해결
2. `project=runs/segment`를 명시로 줬더니 ultralytics 설정의 기본 `runs_dir`("runs")와 겹쳐서 `runs/segment/runs/segment/crack_seg_v1`로 이중 중첩됨 → 이후 `project=`는 생략하고 `name=`만 지정하는 게 안전함 (기본값이 `runs/segment`라 그대로 깔끔하게 떨어짐)
3. **에포크 1 완료 후 체크포인트 저장 단계에서 크래시**: `ModuleNotFoundError: No module named 'polars'` (ultralytics가 학습 결과 CSV 저장에 `polars`를 씀, 근데 안 깔려있었음). 에포크 1 자체는 정상 학습됨(val mAP50 0.242 box / 0.171 mask)인데 가중치 저장 전에 죽어서 `weights/`가 텅 빔 → `pip install --user polars`로 해결, 처음부터 재시작
4. 재시작 후 에포크 1은 정상적으로 `best.pt`/`last.pt` 저장 확인, 에포크 2도 loss 정상 감소 확인
5. **에포크 4 중반, 심각한 리소스 고갈 발생**: 배치 하나가 평소 ~1초에서 9분 넘게 걸리는 등 급격히 느려짐 → 확인해보니 RAM 7.1/7.4GB, **swap 3.7/3.7GB 완전히 소진**, load average 13 (Orin Nano 6코어 기준 과부하). 원인 추정: `yolo segment train`이 기본으로 dataloader worker 6개를 띄우는데, 각 worker가 RAM을 상당히 먹어서(worker당 대략 1GB 안팎) 8GB 통합 메모리에서 감당이 안 된 것으로 보임 (batch=8이 워커 수에 비해 과했을 수도 있음)
6. 몇 분 뒤 **SSH 접속 자체가 완전히 타임아웃 나기 시작함** — sshd 핸드셰이크도 못 받을 만큼 시스템이 맛이 간 것으로 추정. 여러 차례 재시도(수 분간)했지만 재연결 실패. **이 로그를 쓰는 시점까지 Jetson이 계속 응답 없음.**

**현재 상태 (2026-07-12 세션 종료 시점): Jetson 응답 없음, 미해결.** 백그라운드에서 1분 간격 재연결을 계속 시도하도록 해뒀지만, 완전히 멈춘(hard hang) 상태라면 소프트웨어적으로 복구 불가 — **학교 가서 Jetson 전원을 직접 확인/재부팅해야 할 수도 있음.**

**다음 세션에서 이어서 할 것 (우선순위 순):**
1. Jetson 전원 상태 확인 (필요시 재부팅) — 학교에서
2. 재연결되면 `pgrep`으로 학습 프로세스/좀비 프로세스 정리, `free -h`로 메모리 상태 재확인
3. 학습을 **`workers=2`**로 낮춰서 재시작 (메모리 여유 확보가 우선, 필요하면 `batch=4`까지 낮추는 것도 고려). 에포크 1개 도는 동안 `free -h`로 swap이 안정적인지 반드시 확인한 뒤에 그대로 100에포크 진행
4. 학습 완료 후 계획대로: test set 검증 → `vision_ai_node` 라이브 스모크테스트 → 문서화 → 커밋/푸시

## 2026-07-13 세션 — Jetson 복구, 학습 안전 재개, 3개 노드 스켈레톤 구현

**Jetson 복구:** 학교에서 전원 재인가함 (재부팅, uptime 리셋 확인). 좀비 프로세스 없이 깨끗한 상태로 시작.

**학습 안전 재개 체계 구축:**
- 지난 세션에 남아있던 `last.pt`/`best.pt`(epoch 3까지)를 확인 → ultralytics는 매 epoch마다 체크포인트를 자동 저장하고 `resume=True model=last.pt`로 옵티마이저/LR 스케줄까지 그대로 이어받을 수 있음을 소스코드(`trainer.py`의 `check_resume`)로 확인. `workers`/`batch` 등은 resume 시에도 오버라이드 가능(허용 목록에 포함돼 있음).
- `~/bridge_drone_ws/watchdog.sh` 작성: 30초마다 swap 사용률 체크, 80% 넘으면 학습 프로세스에 SIGTERM(15초 후 SIGKILL)을 보내 시스템 전체가 멎기 전에 먼저 학습만 죽임. `nohup setsid`로 학습/watchdog 둘 다 SSH 접속 종료와 무관하게 백그라운드 유지.
- `workers=2 batch=8`로 epoch 4부터 resume. 이후 세션 중간에 카메라 테스트를 위해 두 차례 정지→재개(epoch 22, 23 지점)했고 매번 정상 이어짐. 이 로그를 쓰는 시점 기준 **epoch 41/100**, swap 52% 안정 (한때 32%→51%까지 오르다 멈췄음 — 정확한 원인 미상이나 80% 임계치 대비 여유 있어 계속 진행 중). mask mAP50 0.17(epoch1) → 0.61(epoch41)로 순조롭게 개선 중.
- **주의**: `pgrep -f`로 학습 프로세스를 찾을 때 `nohup setsid <cmd> &` 형태로 띄운 경우 `kill -INT $(pgrep -f '패턴' | head -1)`이 launcher shell(bash) PID를 잡아서 실제 python 프로세스에 신호가 안 갈 수 있음 — 이번에 정지 실패로 한 번 걸림. 실제 python 프로세스 PID를 직접 지정해서 죽여야 확실함.

**카메라 실측거리 재테스트 (학교, 실제 물체 대상):** 지난번 "너무 가까워서 depth=0 → mm값 항상 null"이었던 문제 해결 확인. 실측거리에서 다수 detection에 `length_mm` 실수값이 채워짐. 다만 일반 COCO 물체(의자 5.4m 등) 기준 bbox 방식 정확도는 여전히 들쭉날쭉 — 이는 7/9에 이미 실측 확인된 한계(bbox 변의 중점 두 점이 서로 다른 깊이/물체에 떨어지면 오차 60~70%+)이고, 실제 균열은 평면 위 얇고 긴 형태라 mask 기반(`cv2.minAreaRect`) 경로를 쓰므로 문제가 훨씬 적을 것으로 예상. 균열 전용 모델이 아직 학습 중이라 이번 테스트는 COCO 사전학습 모델(`yolov8n.pt`)로 mm 계산 파이프라인 자체만 검증.

**`web_dashboard` 스켈레톤 구현 (신규):** ROS2 노드가 HTTP 서버(8080, `static/index.html` 서빙)와 WebSocket 서버(8765)를 백그라운드 스레드로 기동. `/vision_ai/detections`(탐지 배열)와 `/drone_core/status`(상태 객체)를 구독해 연결된 브라우저로 그대로 broadcast, `/vision_ai/annotated`는 JPEG 인코딩해서 바이너리 프레임으로 broadcast. 프론트엔드는 메시지가 배열이면 탐지 테이블, 객체면 드론 상태 배지(연결/armed/모드/배터리), 바이너리면 카메라 프레임으로 분기 렌더링 — 자동 재연결 포함. Jetson에서 실제 브라우저(`http://100.79.110.90:8080/`)로 열어서 실시간 갱신까지 육안 확인함. 합성 메시지로 각 경로(탐지/상태/이미지) 엔드투엔드 검증 완료.

**`drone_core` MAVROS 로직 구현:** `ros-humble-mavros-msgs`(+`geographic-msgs`) 설치. `/mavros/state`, `local_position/pose`, `battery` 구독, `/drone_core/status` JSON 발행, **OFFBOARD 모드 유지를 위한 20Hz 연속 setpoint 스트림**(목표 없으면 현재 위치로 hold — PX4가 setpoint 스트림 끊기면 모드 이탈시키는 것 방지) 구현, `arm()`/`set_mode()` 비동기 서비스 클라이언트 추가. FC 미보유로 실비행 검증은 불가하나 import/빌드/status 발행/20Hz 스트림 안정성은 Jetson에서 확인.

**`lidar_mapping` 스켈레톤 구현:** `/scan`(LaserScan) 구독, `/lidar_mapping/status`(연결여부/포인트 수/min-max range) 발행. 실제 SLAM(위치추정+맵생성)은 `slam_toolbox` launch 연동으로 나중에 붙일 예정(RPLIDAR A3 미보유라 미착수) — 이 노드는 원시 스캔 상태 집계까지만. 합성 LaserScan(360포인트, 240 유효)으로 검증.

전부 GitHub에 커밋/푸시 완료.

## 2026-07-13 세션 (계속) — GPS 음영구역 위치추정 아키텍처 + slam_toolbox 연동

**주의 — apt install도 swap을 위험 수위까지 밀어올릴 수 있음:** `ros-humble-slam-toolbox` 설치 중 (rviz/nav2/boost-dev 등 의존성 대거 설치) swap이 2분 만에 54%→80%까지 치솟아 **watchdog이 실제로 발동, 학습 프로세스를 SIGTERM으로 안전하게 정지시킴** (epoch 43 체크포인트는 보존, 데이터 손실 없이 이후 정상 resume). 학습 중엔 무거운 apt 작업도 학습을 먼저 멈추고 하거나, 최소한 설치 직후 몇 분은 swap 추이를 반드시 확인할 것.

**GPS 음영구역 위치추정 아키텍처 결정 및 구현:**
- `slam_toolbox`(라이다 스캔매칭)가 `map→odom` 보정, `drone_core`가 MAVROS `local_position/pose`(FC 자체 EKF)를 `odom→base_link` TF로 발행 — GPS 없이 동작하는 표준 nav2 구성 채택
- `drone_core_node.py`에 `tf2_ros.TransformBroadcaster` 추가, 합성 pose(1.5, -2.0, 3.2)로 TF가 정확히 반영되는 것까지 검증 (`ros2 run tf2_ros tf2_echo odom base_link`)
- `launch/bridge_drone.launch.py`에 `base_link→laser` static TF(실측 전 임시값, z=0.1m)와 `async_slam_toolbox_node` 추가, `config/mapper_params_online_async.yaml` 신규 작성
- RPLIDAR 미보유 + 학습 중 메모리 여유가 빠듯해서 slam_toolbox 자체를 실제로 띄워보진 않음 — launch 파일 문법 파싱과 executable 존재만 확인. **다음에 RPLIDAR 연결되면 최우선으로 라이브 검증할 것**
- 2D→3D 균열 태깅 파이프라인 방향도 정리: 픽셀→카메라 3D(기존 `measure_distance_mm`) → 카메라-바디 extrinsic(미실측) → 이번에 만든 `odom→base_link` TF로 월드좌표 → 3D 맵 태깅. `docs/bridge_drone_project_summary.md` 8번 항목 갱신함.

## 2026-07-13 세션 (계속) — 학습 완료, test set 검증, 크랙 모델 라이브 스모크테스트

**학습 완료 (epoch 100/100, 총 두 번의 중단 후 재개 — 최초 OOM/행, apt 인시던트 — 둘 다 체크포인트로 무손실 복구):**
- mask mAP50 0.649, mAP50-95 0.216 (epoch1: 0.171/0.048)
- Git LFS 새로 셋업해서 `models/crack_seg_v1_yolov8n_seg.pt`로 GitHub에 커밋/푸시 (`results.csv`/`args.yaml`도 학습 기록으로 같이 올림)

**Test set 검증 (112장, 148 인스턴스, 학습에 안 쓰인 홀드아웃):**
- Box: precision 0.872, recall 0.644, mAP50 0.742
- Mask: precision 0.774, recall 0.568, **mAP50 0.593**, mAP50-95 0.21
- 추론 속도 18ms/이미지(GPU) — val(0.649)과 test(0.593) 차이가 크지 않아 과적합 징후 없음

**`vision_ai_node` 크랙 모델 라이브 스모크테스트:**
- 처음엔 depth 유효 픽셀이 프레임 전체의 16.7%뿐이라 mm값이 거의 다 null (163개 중 1개만 값 나옴) — 균열 자체 특성(얇음) 때문이 아니라 **그 순간 카메라 각도/장면이 depth 캡처에 안 좋았던 것**으로 확인 (진단 스크립트로 마스크 내부 depth 유효율까지 직접 측정해서 확인함)
- 카메라를 평평한 벽면 위주로 재조정하니 마스크 내부 depth 유효율 95.4%까지 개선, 이후 재기동한 노드에서 243개 중 81개 detection에 실제 mm값 정상 계산됨 — **depth+측정 파이프라인 자체는 정상 확인**
- 다만 실제 균열이 없는 사무실 환경이라 모델이 천장의 대각선 금속 레일을 "crack 0.36"으로 오탐(캡처 이미지: `crack_model_test_20260713.jpg`, 프로젝트 루트에 저장) — 길고 얇고 대각선인 시각 패턴이 학습한 균열 특징과 일치해서 나온 예상 가능한 오탐. **실제 정확도 검증은 진짜 균열 있는 현장에서 다시 해야 함** (기존에 알던 결론과 동일)

## 2026-07-13 세션 (계속) — 우드락 실측 실험: 근접거리 depth 이중측정 문제 발견

**목적**: 실제 균열이 없어서, 우드락에 자로 잰 정확한 길이(세로 5.5cm=55mm, 가로 폭 3~7mm)의 흠집을 칼로 내서 "실측값 대비 오차"를 정량 검증.

**실험 1 — 카메라~우드락 약 50cm:**
- 균열 위치를 확대+격자 오버레이 이미지로 정확히 픽셀좌표 특정 후 `measurement.measure_distance_mm()`으로 30프레임 반복 측정
- 결과: depth가 약 0.94~0.98m로 읽힘 (실제 50cm의 거의 정확히 2배), 계산된 길이도 평균 108.3mm (실제 55mm의 약 1.97배)
- **원인 추정**: D455F 공식 최소 인식거리(약 50~60cm) 근처/이하에서 스테레오 매칭이 disparity를 잘못 잡아 실제 거리를 약 2배로 과대측정하는 알려진 현상. 첫 프레임 하나에서는 균열 지점 depth가 아예 0(무효)으로 나온 적도 있었는데, 30프레임 반복해보니 29/30은 유효했음(단발성 무효는 그냥 프레임 노이즈, 2배 과대측정 쪽이 진짜 문제).

**실험 2 — 카메라~우드락 약 1.4m (더 멀리 이동 후 재측정):**
- 30/30 프레임 전부 유효, depth 약 1.39~1.40m로 일관됨
- 계산된 길이: 평균 **59.1mm** (58.4~60.7mm) — 실제 55mm 대비 오차 **약 4.1mm (7.5%)**
- 근접거리 문제였던 2배 과대측정이 사라지고 정확도가 실용적인 수준으로 회복됨

**결론 (프로젝트 문서 8번 항목에도 반영):** 카메라-구조물 간 거리가 D455F 최소 인식거리 근처(~50cm 이하)면 depth가 실제 거리의 약 2배로 체계적으로 틀릴 수 있음이 실측으로 확인됨. **실제 비행/스캔 시 카메라-교량 구조물 간 최소 안전거리를 80cm~1m 이상으로 유지해야 함** — 이건 배터리/미션 플래닝(비행 경로, 접근 거리) 설계에 반영해야 하는 실측 제약사항.

## 2026-08-07 세션 — 하드웨어 최종화 문서 반영

RPLIDAR A3/TFmini/GPS 모듈 완전 제외, ELRS 915MHz→2.4GHz 변경, Jetson 전원 MATEK BEC12S-PRO 추가 등 하드웨어가 확정됨 (`docs/hardware_final_spec.md` 신규 작성). 자세한 내용은 그 문서와 `docs/bridge_drone_project_summary.md` 참고 — 이 세션의 핵심은 코드가 아니라 문서 반영이었음.

## 2026-08-07 세션 (계속) — `lidar_mapping`을 D455F 기반 Visual SLAM(RTAB-Map)으로 재구현

하드웨어 최종화로 RPLIDAR가 빠지면서 `lidar_mapping`/`launch`/`config`가 실물과 불일치하던 것을 해결. 전체 설계와 검증 결과는 `docs/bridge_drone_project_summary.md` 4번/8번 항목에 반영, 여기엔 구현 과정에서 겪은 실무 디테일만 기록.

**단일 캡처 지점 도입 (`realsense2_camera`):**
- `ros-humble-realsense2-camera`(4.58.2)를 apt로 설치 — arm64 패키지가 존재해서 D455F용 librealsense를 소스에서 다시 빌드할 필요 없었음(기존 `~/librealsense` 소스 설치와 별도 경로라 충돌도 없음, `apt-get install --dry-run`으로 사전 확인).
- **파라미터명 실측 확인**: 이 버전에서 해상도 지정은 `depth_module.profile`/`rgb_camera.profile`이 아니라 **`depth_module.depth_profile`/`rgb_camera.color_profile`** (구버전 realsense-ros와 다름) — `ros2 param list`로 실제 노드에 물어봐서 확인. 이 이름으로 지정해야 기존 `vision_ai`의 수동 pyrealsense2 설정과 동일한 depth 1280x720 / color 1280x800 @30fps가 나옴.
- 토픽 네임스페이스는 기본적으로 `/camera/camera/...`로 중첩됨(namespace='camera' name='camera' 조합) — realsense-ros 4.x의 기본 동작, 그대로 채택.
- `vision_ai_node.py`를 리팩터링해서 더 이상 `pyrealsense2`로 디바이스를 직접 열지 않고 `message_filters.ApproximateTimeSynchronizer`로 컬러+depth 토픽을 구독하도록 변경. `measurement.py`의 3D 역투영 수학 자체는 그대로 두고, depth 조회만 `depth_frame.get_distance()`(라이브 디바이스 필요)에서 raw depth 배열 + `depth_scale`로 바꿈 — `rs.intrinsics()`는 `CameraInfo`(K 행렬)로 수동 구성.
- 젯슨에서 합성 핀홀 케이스로 수학 검증(65px 간격, fx=650, depth=1m → 예상 100mm, 실제 100.00mm) — 리팩터링이 계산 로직을 깨지 않았음을 확인. 실제 카메라로도 크래시 없이 `/vision_ai/annotated` ~9Hz 발행까지 확인했지만, **원격 세션이라 알려진 크기 물체로 mm 정확도 재검증(우드락 재실험 등)은 못함 — 다음 하드웨어 세션 필요.**

**RTAB-Map 통합 (`rtabmap_odom`/`rtabmap_slam`):**
- `ros-humble-rtabmap-ros`(0.23.7) 설치 중 `Hash Sum mismatch` 발생 — 7/9에 기록한 조선대 캠퍼스 네트워크 필터링 문제와 동일 패턴(`packages.ros.org`), **재시도 2번째 만에 성공**. 이 문제 재발 시 필터부터 의심할 것(계속 유효한 교훈).
- `rgbd_odometry`(자체 Visual Odometry, `odom→base_link` TF+`/odom` 발행)와 `rtabmap`(그 위에 맵빌딩/루프클로징, `map→odom` TF+`/map`) 조합 채택, `drone_core`/MAVROS 완전히 독립 — 이유는 `docs/bridge_drone_project_summary.md` 8번 항목 3 참고(Betaflight FC가 MAVROS와 정상 통신 안 할 가능성).
- 두 노드의 기본 구독/발행 토픽명을 실제로 띄워서 확인(`ros2 node info`) — `rgbd_odometry`는 `/rgb/image`, `/depth/image`, `/rgb/camera_info` 구독, `rtabmap`은 그 위에 `/odom`까지 추가로 구독. `-d`(DB 초기화) 플래그는 `--ros-args` **앞에** 와야 함 — 뒤에 두면 `UnknownROSArgsError`로 크래시(수동 CLI 테스트 중 실수로 겪음, launch파일의 `arguments=[...]`는 launch_ros가 알아서 순서를 맞춰주므로 이 문제 없음).
- `base_link→laser` static TF를 `base_link→camera_link`로 교체(실측 전 placeholder, z=0.05m). `realsense2_camera_node`가 `camera_link→camera_color_optical_frame` 체인을 자체 발행하는 것을 `tf2_echo`로 확인해서, `base_link→camera_link` 하나만 있으면 체인이 완성됨을 검증.
- **7개 노드(카메라, rgbd_odometry, rtabmap, vision_ai, drone_core, lidar_mapping, web_dashboard) 동시 기동 검증**: 크래시 없음, `/odom` 발행 확인, 메모리 안전(swap 거의 안 늚 — 7/12의 학습 OOM 인시던트 같은 문제 재발 안 함, YOLO 동시 구동해도 문제없었음).
- **한계 (원격 세션의 근본적 제약)**: 카메라가 젯슨에 고정된 채 정지 상태라 `rgbd_odometry`의 `quality`가 거의 계속 0(추적 실패/"lost")으로 나옴 → `rtabmap`이 "no odometry is provided, Image 0 is ignored" 에러를 반복 — **이건 코드 버그가 아니라 Visual Odometry의 근본적 특성(움직임+텍스처 필요)** 때문. `odom→base_link`/`map→odom` TF가 실제로 갱신되는지, 루프클로저가 잡히는지는 카메라를 손으로 움직이는 실측이 있어야 확인 가능 — **다음 하드웨어 세션 최우선 항목.**

**`lidar_mapping_node.py` 재작성:** `/scan` 대신 `rtabmap`의 `/info`(`rtabmap_msgs/Info`) 구독으로 전환, `/lidar_mapping/status`(connected + map_node_count + loop_closure 카운트) 발행은 기존 계약 유지. 정상 빌드/구독 확인, `connected:false`(아직 `/info` 발행 전) 정상 출력 확인.

전부 GitHub에 커밋/푸시 완료(단계별로 4개 커밋으로 분리).

## 2026-08-07 세션 (계속) — 2D→3D 크랙 태깅/퓨전 노드 구현

목표: `docs/bridge_drone_project_summary.md` 8번 항목 2(2D 탐지를 3D 지도 좌표로 정합) 구현. 하드웨어 없이 원격으로 진행 가능한 작업이라 이번 세션에 이어서 착수.

- `vision_ai/measurement.py`에 `deproject_point_m(depth_image, depth_scale, intrinsics, point)` 헬퍼 추가 — 기존 `measure_distance_mm()`과 같은 `rs2_deproject_pixel_to_point` 호출 재사용, 단일 픽셀을 카메라 광학 프레임 3D 좌표(m)로 변환. depth 무효(0)면 `None`.
- `vision_ai_node.py`의 `_describe_detection()`에 bbox 중심의 3D 위치(`center_camera_m`)를 계산해 탐지 JSON에 추가 — 기존 `length_mm`/`width_mm`(크기)와 별개로 "위치" 정보가 필요했음.
- `src/lidar_mapping/lidar_mapping/crack_fusion_node.py` 신규: `/vision_ai/detections` 구독, tf2(`camera_color_optical_frame → map`)로 각 탐지의 `center_camera_m`을 `map` 좌표로 변환해 `map_position_m`을 덧붙여 `/crack_fusion/tagged_detections`로 재발행. TF 체인이 없으면(SLAM 미기동 등) 해당 탐지만 조용히 스킵 — 크래시 없음. `/vision_ai/detections`엔 타임스탬프가 없어서 "최신 사용 가능한" TF를 씀(정밀도보다 단순함 우선, 코드 주석에 한계 명시).
- `lidar_mapping` 패키지에 새 노드 등록(`setup.py` entry_points), 의존성 추가(`geometry_msgs`, `tf2_ros`, `tf2_geometry_msgs` — 전부 이미 젯슨에 설치돼 있어서 추가 apt 불필요).
- **검증**: (1) 합성 핀홀 케이스로 `deproject_point_m()` 수학 검증(중심 픽셀→[0,0,1.0]m 등, 예상값과 일치). (2) 젯슨에서 `crack_fusion_node`를 실제로 띄워서 TF가 전혀 없을 때 크래시 없이 조용히 스킵하는 것 확인. (3) **map→odom→base_link→camera_link(z=0.05)→camera_color_optical_frame 합성 TF 체인**(전부 항등변환 + z오프셋 하나)을 4개의 `static_transform_publisher`로 구성해서 실제로 띄우고, 합성 탐지(`center_camera_m: [0.1, 0.2, 1.5]`)를 퍼블리시 → `map_position_m: [0.1, 0.2, 1.55]` 수신, 기대값과 정확히 일치 확인. `ros2 topic echo`의 기본 `--truncate-length`(128자)에 걸려 출력이 잘려서 처음엔 결과를 오독할 뻔함 — 긴 JSON 문자열 토픽 확인할 땐 `--truncate-length` 크게 줄 것(팁으로 기록).
- **미검증**: 실제 SLAM(rgbd_odometry+rtabmap)이 붙은 라이브 환경에서의 동작 — 카메라 정지 상태라 `map`/`odom` 프레임 자체가 안 생겨서 이번 세션엔 못함. 위 "카메라를 실제로 움직이며 RTAB-Map 라이브 검증" 항목에 종속.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-07 세션 (계속) — DeepCrack 파인튜닝 (원격, 하드웨어 불필요)

목표: `docs/bridge_drone_project_summary.md` 5번 항목(드론 앵글 데이터셋 확장) 진행. 원래 후보였던 BCD/UAV-PDD2023을 실측했으나 둘 다 세그멘테이션 학습엔 못 쓴다고 확인:

- **BCD**: Google Drive에서 `gdown --folder`로 실제 다운로드해서 확인 — `train.txt`/`val.txt`가 `파일명\t0또는1` 형식, 이미지도 224×224 패치(`picture1~3.zip`). **SDNET2018과 완전히 동일한 함정**(분류 전용, bbox/마스크 없음). 라벨 분포 확인: 0(no-crack) 3898개, 1(crack) 958개.
- **UAV-PDD2023**: Zenodo(https://zenodo.org/records/8429208, CC BY 4.0)에서 확인 — 2,440장/11,158 인스턴스, **PASCAL VOC bbox 포맷**(세그멘테이션 마스크 없음), 도로 포장 결함(균열/패칭/포트홀) 6종, 드론 30m 고도 촬영. 마스크가 없어서 crack-seg와 바로 합칠 수 없음.
- 대신 이미 알고 있던 **DeepCrack**(`github.com/yhlleo/DeepCrack`, 저장소 자체에 `dataset/DeepCrack.zip` 포함)을 사용. `git clone --depth 1` → 압축 해제 → `train_img`/`train_lab`(300장) + `test_img`/`test_lab`(237장), 마스크는 0/255 단일채널 PNG(파일명은 이미지와 동일, 확장자만 다름). **라이선스 주의: 비상업적 연구/교육 목적으로만 사용 제한** — 나중에 상용화 단계에선 재확인 필요.

**마스크 → YOLO-seg 폴리곤 변환**: `scripts/convert_deepcrack_to_yolo_seg.py` 작성 — `cv2.findContours`로 마스크의 연결된 균열 영역마다 하나의 폴리곤 인스턴스(class 0) 생성, `images/{train,val}`+`labels/{train,val}` 구조로 배치, `data.yaml` 자동 생성. 537장 전부 유효 라벨 생성(빈 라벨 0개), 총 1,743개 인스턴스, 좌표 정규화 범위 확인(0.0~0.998, 정상).

**파인튜닝 (안전 학습 프로토콜 그대로 재사용)**:
- 기존 `runs/segment/crack_seg_v1/weights/best.pt`에서 이어서 학습(주의: 이 체크포인트는 `models/`에 커밋은 됐지만 젯슨엔 원래부터 `runs/segment/crack_seg_v1/weights/`에 남아있던 원본이 있었음 — git으로 젯슨에 내려받은 게 아님, 로컬 파일 그대로 사용)
- `yolo segment train model=runs/segment/crack_seg_v1/weights/best.pt data=datasets/deepcrack_yolo/data.yaml epochs=50 workers=2 batch=8 patience=15 lr0=0.001 name=deepcrack_finetune_v1`
- `optimizer=auto`가 기본이라 지정한 `lr0=0.001`이 무시되고 AdamW lr=0.002로 자동 결정됨(치명적이진 않음, 다음에 명시적으로 고정하려면 `optimizer=AdamW`도 같이 지정할 것)
- `watchdog.sh` 동시 가동, 초반 swap이 0%→28%까지 빠르게 올랐다가(에포크 1~8) **안정적으로 plateau** — 이전 OOM 인시던트만큼 위험하진 않았지만 300장짜리 작은 데이터셋치고는 예상보다 메모리를 씀(`workers=2` 지정했는데 실제로 학습 프로세스 외 자식 프로세스가 6개 떠서 관찰됨 — 검증용 dataloader가 별도로 더 뜨는 것으로 추정, 정확한 원인 미확인). watchdog 발동 없이 자연 종료.
- **결과**: 15에포크에서 최고 성능 도달 후 개선 없어서 30에포크에 EarlyStopping(patience=15) 발동, 총 0.213시간(약 13분) 소요.

**효과 검증 (같은 DeepCrack val 237장 기준 전/후 비교, 다른 테스트셋과 섞지 않고 공정 비교)**:
| | 원본(crack_seg_v1) | 파인튜닝 후(v2) |
|---|---|---|
| Box mAP50 | 0.267 | 0.428 |
| Mask mAP50 | 0.194 | 0.403 |
| Mask recall | 0.223 | 0.411 |
| Mask precision | 0.410 | 0.515 |

전부 뚜렷하게 개선됨 — 파인튜닝이 실제로 효과 있었다는 것을 baseline 비교로 직접 확인. `models/crack_seg_v2_deepcrack_finetune.pt`로 커밋 (Git LFS), 학습 기록(`results.csv`/`args.yaml`)은 `models/training_records/deepcrack_finetune_v1/`에 같이 커밋.

**남은 한계**: DeepCrack이 실제 드론 촬영인지 미확인(문헌상 지상/근접 촬영일 가능성) — 이번 파인튜닝은 "세그멘테이션 성능 자체"는 개선했지만 "드론 각도 일반화"까지 검증된 건 아님. 진짜 드론 앵글 데이터로의 확장은 여전히 열린 과제(UAV-PDD2023을 bbox→대략 마스크로 변환해서 보조로 쓰는 방법 등 다음에 고려 가능).

전부 GitHub에 커밋/푸시 완료.

## 2026-08-07 세션 (계속) — web_dashboard에 3D 태깅 결과 연동 + 잠재 버그 발견/수정

목표: `crack_fusion_node`의 `/crack_fusion/tagged_detections`를 대시보드에서 보이게 연결(파이프라인 완성). `web_dashboard_node`에 구독 추가, `index.html`에 새 테이블(class/confidence/length/width/map x,y,z) 추가 — `map_position_m` 필드 유무로 기존 `/vision_ai/detections`(같은 JSON 배열 형태)와 구분.

**빌드 후 젯슨에서 라이브로 검증하다가 이번 변경과 무관한 기존 버그를 발견함**: `web_dashboard_node`가 웹소켓 연결 집합을 `self._clients`란 이름으로 저장하는데, 이게 `rclpy.node.Node`가 내부적으로 쓰는 `_clients`(ROS2 서비스 클라이언트 목록) 속성과 이름이 겹침. `Node.__init__()` 이후에 `self._clients = set()`로 덮어써서, rclpy 실행기가 나중에 자기 내부 클라이언트 목록인 줄 알고 순회하다가 `AttributeError: 'ServerConnection' object has no attribute 'handle'`로 크래시(노드가 기동 직후 죽음). 2026-07-13 세션엔 왜 안 걸렸는지는 불명(그때는 브라우저로 짧게 확인만 하고 끝났을 가능성) — 이번처럼 실제로 몇 분 이상 떠 있게 두고 rclpy executor가 특정 콜백 사이클을 도는 상황에서 터지는 것으로 추정.

**수정**: `self._clients` → `self._ws_clients`로 전부 리네임(충돌 회피), 코드에 왜 `_clients`란 이름을 쓰면 안 되는지 주석으로 명시(재발 방지).

**검증**: 디버그 print를 임시로 넣어서 (1) 클라이언트 연결이 핸들러에 정상 도달하는지, (2) 브로드캐스트가 실제로 클라이언트 수만큼 순회하는지 직접 확인. 이후 파이썬 `websockets` 클라이언트로 3가지 메시지 타입(`/crack_fusion/tagged_detections`, `/vision_ai/detections`, `/drone_core/status`)을 순서대로 발행해서 전부 정확히 수신되는 것 확인 — 웹소켓 브로드캐스트 경로 자체는 정상. **주의**: 첫 시도에서 원격 SSH 명령 사이의 왕복 지연 때문에 테스트 클라이언트의 타임아웃이 발행 전에 만료되는 것을 실제 버그로 착각할 뻔함 — 원격 라이브 테스트에서 클라이언트 타임아웃은 SSH round-trip 여유를 넉넉히 잡을 것(교훈으로 기록).

브라우저 프론트엔드 자체(`index.html`의 `renderTagged()` 렌더링)는 메시지 포맷/전달까지만 확인했고 실제 브라우저 렌더링은 원격이라 육안 확인 못함 — 다음 하드웨어 세션에서 확인.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-07 세션 (계속) — UAV-PDD2023 보조 데이터 실험 (메모리 인시던트 + 최종 폐기)

목표: DeepCrack 파인튜닝으로 부족했던 "진짜 드론 앵글" 세그멘테이션 데이터 문제를 UAV-PDD2023(bbox만 있음, 앞서 5번 항목에서 세그멘테이션 부적합 판정)으로 보완 시도 — bbox를 직사각형 폴리곤으로 근사해서라도 드론 앵글 노출을 늘려보자는 실험.

**다운로드**: Zenodo(2.1GB, `https://zenodo.org/records/8429208/files/UAV-PDD2023.zip`)에서 젯슨으로 직접 wget — 처음엔 100초 만에 35MB만 받혀서(예상 소요 93분) 캠퍼스망 속도 문제로 의심, `wget -c`(재개 가능)로 백그라운드 전환해서 완료까지 기다림(실제로는 훨씬 빨리 끝남, 초반 속도 측정이 오해였던 듯). PASCAL VOC XML(`Annotations/`) + `JPEGImages/` + 공식 `ImageSets/Main/{train,val,test}.txt` 분할(1561/391/488장) 확인. 클래스: Longitudinal/Transverse/Oblique/Alligator crack(균열, 총 8,429 train+val 인스턴스로 필터링) + Pothole/Repair(제외, 이 프로젝트 스코프 아님).

**변환**: `scripts/convert_uavpdd_to_yolo_seg.py` — VOC bbox를 4개 꼭짓점 직사각형 폴리곤으로 그대로 YOLO-seg 라벨에 씀(진짜 마스크가 아니라 근사임을 스크립트 docstring에 명시). 1,952장 변환, 크랙 인스턴스 8,429개.

**메모리 인시던트 (1차 시도, `batch=8 workers=2` — DeepCrack 때와 동일 설정)**: swap이 24%→62%까지 약 7분 만에 가속하며 상승(DeepCrack 때는 27~28%에서 안정화됐던 것과 다름) — watchdog의 80% 임계치를 기다리지 않고 에포크 2 시점에서 직접 SIGTERM으로 선제 정지(체크포인트 보존됨, 데이터 손실 없음). **원인 추정**: UAV-PDD2023 원본 이미지가 2592×1944로 DeepCrack(384×544)보다 픽셀 수 기준 약 35배 커서, 같은 `workers=2`라도 디코딩/캐싱 부담이 훨씬 큼 — 이전 인시던트(7/12, dataloader worker 수 문제)와는 다른 원인.

**재시도 (`batch=4 workers=1`)**: swap이 처음부터 끝까지 25~29%대에서 거의 완전히 평평하게 유지됨(약 1시간 이상 관찰) — 배치/워커 축소가 확실히 효과 있었음. 50 에포크 전부 정상 완료(조기 종료 없음, 총 약 3시간 소요 — 에포크당 3.5~4분, DeepCrack보다 훨씬 느림. 원인은 batch=4로 줄인 것과 이미지가 큰 것 둘 다).

**결과 — baseline 비교로 실제 효과 검증**:
| 평가 대상 | UAV-PDD2023 val mask mAP50 | DeepCrack val mask mAP50 |
|---|---|---|
| 원본(crack_seg_v1) | ~0 (9.87e-06) | 0.194 |
| DeepCrack 튜닝(v2) | (미평가) | 0.403 |
| **UAV-PDD 튜닝** | **0.338** | **~0 (6.24e-07)** |

UAV-PDD2023 자체 도메인 적응은 확실히 성공(mask mAP50 0→0.338)했지만, **같은 모델을 DeepCrack에 돌려보니 완전히 붕괴** — catastrophic forgetting으로 근접 촬영 균열 세그멘테이션 능력을 거의 다 잃음. 직사각형 마스크(진짜 균열 형태와 거리가 멂) + 도메인 격차(UAV-PDD2023은 30m 상공에서 도로를 내려다본 것, 이 프로젝트는 D455F로 80cm~1m 근접 촬영) 둘 다 원인으로 추정. **결론: 폐기, 모델 커밋 안 함.** 실험 자체는 "드론에서 찍은 데이터라고 다 도메인이 맞는 건 아니다"라는 교훈으로 문서화(`docs/bridge_drone_project_summary.md` 5번 항목).

전부 GitHub에 커밋/푸시 완료(모델 자체는 제외, 실험 기록만).

## 2026-08-08 세션 — 코드 리뷰 회귀 수정 + 커버리지 그리드 구현

`/code-review high`로 전날(2026-08-07) 커밋들(SLAM 재구현~UAV-PDD2023 실험)을 정확성 관점에서 검토, 6개 발견 중 2개가 실제 회귀 버그였음:

**1. `vision_ai_node` executor 재블로킹 (심각)**: 카메라 캡처를 realsense2_camera 구독으로 옮기면서, YOLO 추론(`self._model(...)`)을 구독 콜백(`_on_frames`) 안에서 그대로 동기 호출하게 방치 — 원래 "백그라운드 스레드에서 캡처+추론해서 executor 절대 안 블록" 설계 원칙이 리팩터링 과정에서 깨져 있었음. **수정**: 구독 콜백은 cv_bridge 디코딩만 하고 최신 프레임 쌍을 `threading.Event`로 별도 추론 스레드에 넘기는 구조로 복원(`_inference_loop`). 검증: `/vision_ai/annotated`가 카메라+vision_ai 동시 구동 시 `9.982Hz, std dev 0.0033s`로 목표 10Hz에 거의 정확히 맞고 지터도 매우 작음(수정 전엔 지터가 더 컸음) — executor가 더 이상 추론 시간에 끌려다니지 않는다는 걸 확인.

**2. `crack_fusion_node` TF 대기 자기 자신 봉쇄 (심각, subtle)**: `buffer.transform(..., timeout=0.2s)`로 최대 0.2초 블로킹 대기하는데, 노드가 싱글스레드 executor(`rclpy.spin(node)`)로 돌면 그 대기 중엔 TF 리스너 자신의 구독 콜백도 같은 스레드를 못 얻어서 못 돔 — 즉 "기다리는 동안 정작 기다리는 메시지가 도착할 방법이 없는" 자기 자신을 막는 구조. 캐시에 이미 있는 TF는 즉시 반환되니 평소엔 티가 안 나지만, 지금 프로젝트가 막혀있는 바로 그 상황(카메라 정지→SLAM lost→TF 막 복구되는 순간)에서 정확히 문제가 됨. **수정**: `main()`에서 `MultiThreadedExecutor`로 spin. 합성 TF 체인으로 회귀 테스트해서 기존 결과(`map_position_m: [0.1, 0.2, 1.55]`)와 정확히 동일하게 나오는 것 확인.

**나머지 4개(경미)도 같이 수정**: `vision_ai`의 `depth_scale_m_per_unit`을 하드코딩 상수에서 ROS 파라미터로 전환(카메라별로 다를 수 있는 값을 숨겨진 상수로 두지 않기 위함), 워밍업 프레임 스킵 로직 복원(`WARMUP_FRAME_COUNT=30`, pyrealsense2 직접 캡처 시절 있던 걸 리팩터링하며 빠뜨렸었음), `convert_deepcrack_to_yolo_seg.py`에 `cv2.imread` None 체크 추가(파일 누락/손상 시 조용히 스킵하고 계속 진행하도록), `web_dashboard_node`의 4개 근이중복 브로드캐스트 핸들러를 토픽 구독 시 재사용하는 콜백 하나(`_relay_text`)로 통합.

**커버리지 그리드 기능 구현**: 문서(5번 항목)에 설계만 있던 걸 코드로 — `lidar_mapping/coverage_grid_node.py` 신규. `map→base_link` TF를 1Hz로 조회해서 현재 위치가 속한 격자 칸(기본 1.5m, docs 8번 항목 6의 D455F 커버리지 추정치에서 절충)을 누적 집합에 추가, `/coverage_grid/status`(칸 수+추정 면적+칸 좌표 목록 JSON)로 발행. `web_dashboard`에 캔버스 기반 시각화 연동(칸 좌표를 캔버스에 자동 스케일해서 채워진 사각형으로 그림). 카메라 자세/실측 거리는 반영 안 하는 단순화(위치 하나당 칸 하나)임을 코드 주석에 명시. **검증**: 합성 TF로 두 위치(원점 근처, 멀리 이동)를 시뮬레이션해서 칸 계산(`floor(x/1.5)`)과 누적 집합 둘 다 정확함을 확인 — 실제 비행 중 시각화가 유용한 해상도인지는 라이브 검증 필요.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-08 세션 (계속) — 온보드 레코딩 파이프라인 구현

목표: 저장용량 "계산"만 있고 실제로 영상을 저장하는 코드가 없던 걸 구현(docs 8번 항목 8).

- 젯슨의 OpenCV가 FFmpeg/GStreamer 둘 다 빌드에 포함돼 있는 것 확인. `nvv4l2h264enc`(젯슨 하드웨어 H.264 인코더) GStreamer 플러그인은 미설치라 하드웨어 가속 인코딩 경로는 막혀있음 — 대신 `cv2.VideoWriter(fourcc='avc1')`가 FFmpeg 백엔드로 소프트웨어 H.264를 문제없이 뽑아내는 것 확인(`ffprobe`로 `codec_name=h264` 검증).
- `vision_ai/recorder_node.py` 신규: `/camera/camera/color/image_raw` 구독, 큐+백그라운드 스레드로 인코딩(vision_ai_node와 같은 이유 — 구독 콜백 안에서 무거운 작업 동기 실행하면 executor 블록됨, 오늘 코드 리뷰에서 실측 확인한 패턴을 미리 회피). 큐 꽉 차면 오래된 프레임부터 버림(실시간성 우선).
- **실측 검증**: 젯슨에서 실제 카메라로 8.6초 녹화 → `ffprobe`로 확인: `h264`, `1280x800`, `30fps`, **비트레이트 약 15.1Mbps** — docs 8번 항목의 20Mbps 가정보다 낮게 나와서(시간당 약 6.8GB) 저장용량 추정치가 오히려 여유 있는 방향이었음을 실측으로 확인.
- launch 파일에 기본 포함 — 개발/벤치 테스트 중에도 계속 녹화되니 디스크 용량 주기적 확인 필요(코드 주석에도 명시).

전부 GitHub에 커밋/푸시 완료.

## 2026-08-08~09 세션 — dacl10k 발견, catastrophic forgetting 재확인, DeepCrack+dacl10k 동시 학습으로 해결

목표: "근접 촬영+드론앵글+세그멘테이션" 데이터셋을 계속 찾다가 훨씬 좋은 후보(dacl10k)를 발견, 시도하는 과정에서 UAV-PDD2023 때와 같은 forgetting 문제가 재발했고 이번엔 근본 원인(순차 파인튜닝)까지 짚어서 해결함.

**dacl10k 발견**: WACV 2024 벤치마크, 9,920장(train 6,935/val 975/test 2,010), 19클래스 멀티라벨 세그멘테이션, 실제 독일 교량 점검 아카이브(엔지니어링 업체+지자체, 2000~2020년). 논문에 "close-range or telephoto images provide local high-resolution details for crack recognition"이라고 명시 — 지금까지 시도한 것 중 처음으로 "근접 촬영"이 문헌에 확인된 데이터셋. CC BY-NC 4.0, AWS S3(`https://dacl10k.s3.eu-central-1.amazonaws.com/dacl10k-challenge/dacl10k_v2_devphase.zip`, 5.1GB)에서 가입 없이 직접 다운로드. labelme 포맷 폴리곤(`{"label": "Crack", "shape_type": "polygon", "points": [[x,y],...]}`) — Crack 클래스만 추출(`scripts/convert_dacl10k_to_yolo_seg.py`), Crack이 있는 이미지만 사용(train 1,727장/val 254장, 3,626 인스턴스 — 나머지 대다수는 다른 손상 유형이라 이 프로젝트엔 배경 이미지로서의 가치가 낮다고 판단해서 제외).

**dacl10k 단독 파인튜닝 (`batch=4 workers=1`, DeepCrack보다 큰 1600x1200 이미지라 처음부터 안전 설정 적용)**:
- swap 24%→68%까지 완만하게 상승(급격한 스파이크 없음), 50 에포크 전부 정상 완주(조기 종료 없음)
- **자체 val 기준**: mask mAP50 0.028(원본)→0.203(7배 이상) — 확실한 개선
- **DeepCrack 교차검증(baseline 비교로 forgetting 여부 확인하는 이번 세션 표준 절차)**: 0.194(원본)→0.016 — UAV-PDD2023(6.24e-07까지 붕괴)만큼 심각하진 않지만 명백한 퇴보. **순차 파인튜닝은 매번 이전 도메인을 잊는다**는 패턴이 이번에도 재현됨.

**근본 해결 — DeepCrack+dacl10k 동시(joint) 학습**: 순차 파인튜닝(A로 튜닝→B로 다시 튜닝)이 아니라, 두 데이터셋을 처음부터 하나의 학습 세트로 합쳐서(`datasets/combined_yolo/`, DeepCrack 537장 + dacl10k Crack 1,981장 = train 2,027장/val 491장, 파일명 접두사가 서로 달라 충돌 없이 단순 복사로 병합) `crack_seg_v1`에서 한 번만 파인튜닝. 같은 안전 설정(batch=4, workers=1)으로 50 에포크 전부 완주, swap 24%→71%로 역시 위험 수위 안 감(이번 세션 3번째 대형 학습인데도 매번 같은 안전 프로토콜로 안정적).

**결과 — forgetting 없이 양쪽 다 개선**:
| | DeepCrack val mask mAP50 | dacl10k val mask mAP50 |
|---|---|---|
| 원본(crack_seg_v1) | 0.194 | 0.028 |
| 각 데이터셋 단독 파인튜닝(최고 성능) | 0.403 | 0.203 |
| 반대쪽에서 평가(forgetting 확인용) | 0.016 (dacl10k 튜닝 모델) | — |
| **동시(joint) 학습** | **0.328** | **0.171** |

동시 학습이 각 전용 모델의 최고 성능엔 살짝 못 미치지만(당연한 트레이드오프 — 한 도메인에 올인하지 않으니까), **forgetting이 전혀 없고 원본 대비 양쪽 다 크게 개선**(DeepCrack +69%, dacl10k +511%). 이 프로젝트처럼 여러 소스의 크랙 데이터를 계속 추가해나가야 하는 상황에선 순차 파인튜닝보다 "매번 전체 데이터를 합쳐서 재학습"하는 쪽이 안전하다는 걸 실측으로 확인 — **앞으로 새 크랙 데이터셋을 추가할 때도 이 방식(합쳐서 재학습)을 기본으로 삼을 것**.

**채택**: `models/crack_seg_v3_combined_finetune.pt`로 커밋(Git LFS), `launch/bridge_drone.launch.py`의 `vision_ai` 기본 모델 교체(v2→v3). 학습 기록은 `models/training_records/combined_finetune_v1/`.

**메모리 안전 노트**: dacl10k(1600x1200)와 UAV-PDD2023(2592x1944) 둘 다 DeepCrack(384x544)보다 훨씬 큰 이미지라, 처음부터 `batch=4 workers=1`로 시작하는 게 안전함을 확인 — 이미지가 크면 `batch=8 workers=2`(DeepCrack 땐 안전했던 설정)도 위험할 수 있음(UAV-PDD2023 1차 시도에서 swap 24%→62%로 7분 만에 치솟아 수동 개입했던 사례). **앞으로 새 데이터셋 학습 시 이미지 해상도부터 확인하고 크면(1000px 이상 등) 처음부터 `batch=4 workers=1`로 시작할 것.**

전부 GitHub에 커밋/푸시 완료. 이 세션은 사용자가 잠든 사이 자율적으로 진행 지시를 받아 판단부터 실행까지 전부 자동으로 수행함(dacl10k 채택 여부, 모델 커밋 여부 등).

## 다음에 이어서 할 것

- [x] ~~Jetson 응답 없음 문제 해결~~ — 전원 재인가로 복구, watchdog으로 재발 방지
- [x] ~~균열 세그멘테이션 학습~~ — epoch 100 완료, test set 검증까지 끝남 (mask mAP50 0.593)
- [x] ~~카메라 실측거리 재테스트~~ — depth null 문제 해결 확인
- [x] ~~mask 기반 measurement 라이브 검증~~ — depth 유효한 장면에서 정상 작동 확인
- [x] ~~측정 정확도 실측 검증(우드락)~~ — 완료: 1.4m 거리에서 7.5% 오차 확인, 단 50cm 근접시 2배 과대측정 문제 발견
- [x] ~~`web_dashboard` 스켈레톤 만들기~~ — 완료 (탐지 테이블 + 카메라 스트리밍 + 드론 상태 배지)
- [x] ~~하드웨어 최종화 (RPLIDAR/TFmini/GPS 제외, ELRS 2.4GHz, BEC 추가)~~ — 2026-08-07 확정, 문서 반영 완료
- [x] ~~`lidar_mapping`을 D455F 기반 Visual SLAM(RTAB-Map)으로 재구현~~ — 2026-08-07 완료, 구조적 검증까지 끝남
- [x] ~~2D→3D 크랙 태깅/퓨전 로직 구현~~ — 2026-08-07 완료, 합성 TF 체인으로 수학 검증까지 끝남
- [x] ~~드론 앵글 데이터셋 파인튜닝~~ — BCD/UAV-PDD2023 둘 다 세그멘테이션 부적합 확인, DeepCrack으로 대체 파인튜닝 완료(mask mAP50 0.194→0.403, baseline 비교로 효과 검증). 단, DeepCrack이 진짜 드론 앵글인지는 미확인 — 아래 항목 참고
- [x] ~~진짜 드론 앵글 세그멘테이션 데이터 확보 시도(UAV-PDD2023)~~ — 폐기, 대신 dacl10k 발견(아래 참고)
- [x] ~~dacl10k 발견 + DeepCrack와 동시 학습으로 catastrophic forgetting 해결~~ — `crack_seg_v3_combined_finetune.pt`로 채택, launch 기본 모델 교체 완료(mask mAP50 DeepCrack 0.194→0.328, dacl10k 0.028→0.171, forgetting 없음)
- [x] ~~web_dashboard에 3D 태깅 결과 연동~~ — 완료, 겸사겸사 기존 `self._clients` 네이밍 충돌 버그(크래시)도 발견/수정. 브라우저 실제 렌더링 육안 확인은 다음 하드웨어 세션에
- [x] ~~2026-08-07 세션 코드 리뷰(정확성) + 회귀 버그 수정~~ — vision_ai executor 재블로킹, crack_fusion TF 자기봉쇄 등 2개 심각 버그 포함 6개 전부 수정
- [x] ~~커버리지 그리드 기능 구현~~ — `coverage_grid_node` 신규, `web_dashboard` 캔버스 시각화 연동. 합성 TF로 계산 로직만 검증, 실제 해상도 적절성은 라이브 검증 필요
- [x] ~~온보드 레코딩 파이프라인 구현~~ — `recorder_node` 신규, 실측 비트레이트 15.1Mbps로 저장용량 추정치 검증까지 완료
- [ ] **카메라를 실제로 움직이며 RTAB-Map 라이브 검증 (최우선, 다음 하드웨어 세션)** — TF 갱신/루프클로저/드리프트, 위 "한계" 참고. `crack_fusion_node`의 라이브(합성 아닌 실제 SLAM) 검증도 여기 종속
- [ ] **vision_ai mm 측정 정확도 재검증(우드락 재실험 등)** — 카메라 캡처 리팩터링(단일화) 이후 아직 실물로 확인 못함
- [ ] 실제 균열 있는 현장에서 재검증 — 우드락 실험은 인공 흠집이라 참고용. 최소 80cm~1m 거리 유지 필수
- [x] ~~학습된 균열 모델로 BCD/UAV-pdd2023(드론 앵글) 파인튜닝 확장 여부 결정~~ — 결정함(둘 다 부적합/폐기), 위 항목들 참고. 근접+드론앵글+세그멘테이션을 동시에 만족하는 데이터셋은 여전히 못 찾음
- [x] ~~배터리/미션 플래닝, 온보드 저장용량 계산~~ — 2026-08-07 1차 추정치 작성 완료(전부 계산 기반, 실측 아님). `docs/bridge_drone_project_summary.md` 6/8번 항목 참고
- [x] ~~착륙 후 정밀 3D 재구성 파이프라인 구현~~ — `scripts/reconstruct_from_flight.sh`(`rtabmap-export` 감싸서 포인트클라우드+텍스처메쉬+비행경로 추출), 스크립트 메커니즘은 젯슨에서 확인. 실제 오도메트리가 있는 `.db`로 진짜 재구성 결과 보는 건 라이브 SLAM 검증(위 항목)과 같이 다음 하드웨어 세션에
- [ ] 드론/RPLIDAR는 최종 제외됐지만, FC(Betaflight) 연결 테스트는 여전히 필요 — 단 `drone_core`/MAVROS 문제(위 참고)부터 정리해야 의미 있음
- [ ] 남은 미해결 설계 이슈 — D455F↔`base_link` extrinsic 실측, ELRS 2.4GHz/WiFi 간섭 실측(우선순위 상승), 배터리/저장용량 추정치를 실측으로 갱신

## 2026-08-09 세션 (계속) — 착륙 후 3D 재구성 파이프라인 구현

사용자가 "착륙 후 3D화 시키는 것도 만들었냐"고 물어봐서 확인해보니, 문서(5번 항목)엔 "착륙 후엔 저장해둔 원본 데이터를 옮겨서 정밀 3D 맵 재구성"이라는 설계 의도만 있었고 실제 코드는 없었음 — `recorder_node`/`rtabmap -d`가 "재료"(영상, 맵 DB)만 모아두고 있었을 뿐, 그걸 가공하는 단계 자체가 빠져있었던 것.

**구현**: `scripts/reconstruct_from_flight.sh` — apt로 이미 설치된 `ros-humble-rtabmap-ros`에 `rtabmap-export`라는 CLI가 함께 들어있는 걸 확인(`/opt/ros/humble/bin/rtabmap-export`, `source /opt/ros/humble/setup.bash` 해야 라이브러리 경로가 잡혀서 실행됨 — 처음에 이걸 빼먹고 실행해서 `librtabmap_core.so.0.23` 못 찾는다는 에러를 겪음). `rtabmap-export --cloud`(포인트클라우드), `--mesh --texture`(텍스처 메쉬), `--poses`(비행 경로) 세 번 호출해서 결과물을 한 출력 디렉토리에 모으는 얇은 래퍼.

**검증**: 아까 launch 파일 검증 테스트 때 생긴 `~/.ros/rtabmap.db`(532KB)로 실제 실행해봄 — 스크립트 자체는 정상 동작(출력 디렉토리 생성, `rtabmap-export` 정상 호출)했지만 `rtabmap-export`가 "The are no odometry poses!? Aborting..."로 실패함. **원인은 스크립트가 아니라 그 `.db`의 한계**: 그 테스트는 카메라가 계속 정지 상태였던 launch 검증용이라 `rgbd_odometry`가 한 번도 제대로 추적(quality>0)을 못 했고, 그래서 저장된 포즈 자체가 없음 — 애초에 재구성할 실제 궤적 데이터가 DB에 없는 게 당연함. 스크립트가 이 실패를 명확한 에러 메시지와 함께 정상적으로 전파하는 것까지 확인(조용히 빈 결과를 내지 않음).

**결론**: 파이프라인 배관(rtabmap-export 호출 체인)은 완성/검증됐지만, **실제로 쓸모 있는 3D 모델이 나오는지는 카메라를 움직인 진짜 비행/워크스루 데이터가 있어야 확인 가능** — RTAB-Map 라이브 검증(TF 갱신, 루프클로저 등)과 정확히 같은 전제조건에 묶여 있음. 다음 하드웨어 세션에서 실제로 걸어다니며 SLAM을 돌린 뒤 이 스크립트로 바로 이어서 검증할 것.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-09 세션 (계속) — 재구성 결과물 컨셉 시각화 + 텍스처 부족 SLAM 위험 식별

사용자에게 착륙 후 3D 재구성 파이프라인이 실제로 어떤 걸 만들어내는지 보여달라는 요청을 받아, 젯슨 원격 아티팩트로 컨셉 시각화 2개를 만듦(코드 변경 없음, `docs`/`web_dashboard` 자산과는 별개 — Claude 아티팩트 프리뷰).

1차 시도는 추상적인 점구름(concrete texture noise + 랜덤 크랙 점들)으로 만들었는데, 사용자가 "실제 교량처럼 다리 형태가 3D로 있고 균열이 실제 보이는 것처럼"이 목표라고 명확히 함 — 거더(보) 4개 + 데크로 구성된 인식 가능한 지오메트리(순수 canvas 2D, 직접 짠 원근 투영으로 회전 가능)로 재작업, 균열도 점 무더기 대신 거더 표면 위의 검은 지그재그 선(실제 흠집처럼)으로 다시 그림. 기본 시점도 드론이 실제로 촬영하는 각도(다리 아래에서 위를 올려다보는)로 맞춤.

**사용자가 "실제로 저렇게 나올까?"라고 되물어서, 처음에 했던 "진짜 촬영한 모습 그대로 나온다"는 답변을 스스로 정정함**: `--texture`가 실제 사진을 입히는 건 맞지만, 그게 곧 깔끔한 결과를 보장하진 않음 — 이 프로젝트 고유의 두 가지 위험 요소를 논리적으로 새로 식별:

1. **텍스처 없는 콘크리트 표면 = Visual SLAM 실패의 전형적 조건**: 균일한 회색 콘크리트 교량 하부는 특징점이 거의 없어서 `rgbd_odometry`가 트래킹을 잃거나 드리프트할 위험이 이론상 큼. 2026-07-13에 이미 겪은 "depth 유효 픽셀 16.7%(안 좋은 장면) → 95%(평평한 벽)"처럼 장면에 따라 결과가 크게 갈렸던 전례가 SLAM 트래킹에도 그대로 적용될 가능성이 높다고 판단.
2. **mm급 균열이 촬영 거리(80cm~1.4m)의 사진 해상도로 텍스처에 선명하게 찍힐지 미검증**: GSD(픽셀당 실제 거리) 문제라 실측 전엔 모름 — `vision_ai`의 실시간 세그멘테이션+측정은 이미 검증됐지만, 그 결과를 3D 모델 텍스처에서 "육안으로도" 알아볼 수 있는지는 별개 문제.

둘 다 `docs/bridge_drone_project_summary.md`에 반영(8번 항목 1, 3). **핵심 교훈**: 컨셉 시각화를 만들 때 "이렇게 될 것"이라고 과신하지 말고, 실측 전까지는 구조/형식만 보여주는 것과 품질을 보장하는 것을 명확히 구분해서 전달할 것 — 사용자가 되물어봐서 스스로 정정한 사례.

전부 GitHub에 커밋/푸시 완료(문서만, 아티팩트 자체는 이 세션의 대화 미리보기 링크로만 존재).
