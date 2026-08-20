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
- [x] ~~web_dashboard에 3D 태깅 결과 연동~~ — 완료, 겸사겸사 기존 `self._clients` 네이밍 충돌 버그(크래시)도 발견/수정.
- [x] ~~web_dashboard 브라우저 실제 렌더링 육안 확인~~ — 2026-08-12 완료! 이 Mac이 젯슨과 Tailscale로 직접 연결돼 있어서 헤드리스 Chrome(Playwright)으로 실제 확인 가능했음. 레이아웃/캔버스/테이블 전부 정상, 콘솔 에러 없음. 스크린샷: `docs/screenshots/web_dashboard_2026-08-12.png`
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

## 2026-08-12 세션 — 실제 브라우저로 web_dashboard 렌더링 최초 확인 (헤드리스 Chrome)

지금까지 "브라우저 실제 렌더링 육안 확인"이 원격 세션의 근본적 한계로 계속 남아있었는데, 이 Mac이 젯슨과 같은 Tailscale 네트워크에 **직접(P2P) 연결**돼 있는 걸 발견해서 해결함(`tailscale status`로 `100.79.110.90`이 "active; direct"로 표시되는 것 확인, ping도 정상 왕복). 즉 SSH뿐 아니라 HTTP/WebSocket도 이 Mac에서 젯슨으로 직접 도달 가능 — Playwright로 로컬에 설치된 실제 Google Chrome(151.x)을 헤드리스로 띄워서 진짜 `http://100.79.110.90:8080/`을 열어봄.

**검증 방법**: 젯슨에 `realsense2_camera`(실제 D455F) + `vision_ai_node`(실제 `crack_seg_v3` 모델) + `drone_core_node` + `web_dashboard_node`를 띄우고, RTAB-Map 없이도 렌더링 경로를 다 확인하기 위해 `/coverage_grid/status`·`/crack_fusion/tagged_detections`·`/vision_ai/detections`에 합성 메시지를 추가로 발행(SLAM 의존 노드는 실제 모션이 없어 데이터가 안 나오므로).

**첫 시도 함정**: 브라우저가 웹소켓에 연결되기 *전에* 발행한 합성 메시지는 아예 못 받음 — `web_dashboard_node`가 최신값을 캐시하지 않는 순수 릴레이(`_relay_text`, 클라이언트 있을 때만 방송)라서, 연결 전에 지나간 메시지는 유실되는 게 정상 동작. **교훈**: 이 노드 특성상 브라우저가 늦게 붙으면 그 직전 상태(마지막 탐지, 마지막 커버리지 등)를 못 받음 — 실제 운영에서 대시보드를 나중에 열면 "최근 상태"가 아니라 "그 이후 갱신"만 보이게 된다는 뜻. 지금 우선순위는 아니지만, 나중에 "최근 스냅샷 캐시" 기능이 필요할 수 있음(참고용으로만 기록, 지금 구현 안 함).

**결과**: 브라우저 연결 후 재발행하니 전부 정상 렌더링 확인 — 드론 상태 배지(색상 코딩 포함), **커버리지 그리드 캔버스가 실제로 정확한 격자 모양으로 그려짐**(보낸 칸 좌표와 스크린샷의 초록 칸 배치가 정확히 일치, 캔버스 자동 스케일링 로직 문제없음 확인), 실시간 카메라(진짜 D455F 화면, 사무실 천장/바닥), 3D 태깅 테이블(숫자 포맷팅까지 정상). 탐지 결과 테이블은 실제 카메라 앞에 진짜 균열이 없어서 빈 상태로 나왔는데, 이것도 실은 좋은 신호 — 합성 탐지 메시지를 보내도 실제 `vision_ai_node`가 10Hz로 계속 진짜(빈) 결과를 덮어써서, 실시간 파이프라인이 실제로 우선권을 갖고 있다는 걸 확인시켜줌. 콘솔 에러/리소스 404 없음. 스크린샷은 `docs/screenshots/web_dashboard_2026-08-12.png`로 저장.

**의의**: 2026-08-07부터 미해결로 남아있던 "web_dashboard 브라우저 실제 렌더링" 항목이 완전히 해소됨 — 남은 건 이제 실제 SLAM 라이브 데이터(카메라 이동)로 3D 태깅/커버리지가 자연스럽게 채워지는지뿐이고, 그건 여전히 하드웨어 세션 필요.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-12 세션 (계속) — RTAB-Map 저텍스처 튜닝 + config 파일 분리

지난 세션에 논리적으로 식별한 "텍스처 없는 콘크리트 = SLAM 실패 조건" 위험에 실제로 대응. 웹 검색으로 나온 파라미터 추천은 요약 과정에서 이름이 부정확할 수 있다고 판단해서, **젯슨에 실제로 노드를 띄우고 `ros2 param list`/`describe`/`get`으로 진짜 파라미터명과 기본값을 직접 조회**하는 방식으로 검증(`rgbd_odometry`, `rtabmap` 둘 다 확인) — 이렇게 하니 `Vis/MinInliers`(기본 20), `GFTT/QualityLevel`(기본 0.001, 이미 관대함), `Odom/Strategy`(기본 0, Frame-to-Frame) 등 정확한 현재값을 근거로 조정할 수 있었음.

**핵심 발견**: `Odom/Strategy`가 기본 0(Frame-to-Frame, 직전 프레임하고만 비교)인데, RTAB-Map 위키에 따르면 저텍스처/특징점 부족 환경엔 1(Frame-to-Map, 최근 키프레임 누적 로컬 맵과 비교)이 훨씬 강건함 — 일시적으로 특징점이 부족한 프레임을 지나가도 이전에 본 특징점으로 복구가 쉬워짐. 이걸 1로 바꾸고, `OdomF2M/MaxSize`(로컬 맵 크기) 2000→3000, `Vis/MinInliers` 20→15로 완화. `GFTT/QualityLevel`/`Vis/MaxFeatures` 등은 이미 적절하거나(전자) 8GB 젯슨 메모리 여유 우려로(후자) 그대로 둠 — 근거 없이 다 바꾸지 않고 확인된 것만 조정.

**config 파일로 분리**: 원래 launch.py 안에 인라인 Python dict로 박혀있던 파라미터들 대신, `config/rtabmap_tuning.yaml` 신규 작성해서 `rgbd_odometry`/`rtabmap` 노드의 `parameters=[...]` 리스트에 dict와 함께 파일 경로로 넘김(ROS2 launch가 dict와 yaml 파일 혼합을 지원). **주의**: RTAB-Map의 모든 파라미터는 내부적으로 문자열 타입이라(`ros2 param describe` 결과 전부 `Type: string`), YAML에 `Odom/Strategy: 1`처럼 숫자로 쓰면 안 되고 반드시 `"1"`처럼 따옴표로 문자열 명시해야 함 — 안 그러면 YAML 파서가 정수로 해석해서 타입 불일치가 날 수 있음.

**검증**: 젯슨에서 개별 노드 실행(`--params-file`)과 전체 `ros2 launch` 둘 다로 확인 — `ros2 param get`으로 재조회해서 `Odom/Strategy=1`, `OdomF2M/MaxSize=3000`, `Vis/MinInliers=15`가 두 노드 모두에 정확히 적용된 것 확인, 에러/경고 없음. (`ros2 node list`에 `/rgbd_odometry`가 순간적으로 두 번 뜬 적 있었는데 실제 프로세스는 하나뿐이었음 — discovery 타이밍상 흔한 일시적 현상, 실제 중복 실행 아님.)

**여전히 미검증**: 이 튜닝이 실제로 트래킹 안정성을 개선하는지는 카메라를 움직인 라이브 테스트가 있어야 확인 가능 — 파라미터가 정확히 적용된다는 배관 검증까지만 이번 세션에서 완료.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-12 세션 (계속) — D455F extrinsic을 launch argument로 분리

`base_link→camera_link` static TF의 6개 값(x,y,z,roll,pitch,yaw)이 `launch/bridge_drone.launch.py` 안에 하드코딩돼 있었음(현재는 z=0.05만 있고 나머진 전부 0인 실측 전 임시값). RTAB-Map 파라미터는 YAML로 뺐지만, `static_transform_publisher`는 `arguments`(커맨드라인 인자)로만 값을 받아서 YAML 파라미터 파일 방식이 안 맞음 — 대신 `DeclareLaunchArgument`/`LaunchConfiguration`으로 6개 다 launch 인자화.

**결과**: 나중에 실측 완료되면 `launch/bridge_drone.launch.py`를 전혀 안 건드리고 `ros2 launch launch/bridge_drone.launch.py camera_z:=0.08 camera_pitch:=0.15` 처럼 커맨드라인에서 바로 반영 가능 — 코드 모르는 팀원도 값만 알면 적용 가능해짐. 젯슨에서 두 가지 다 실측 검증: (1) 인자 없이 기본값(z=0.05)이 그대로 나오는지, (2) `camera_z:=0.12 camera_pitch:=0.15` 오버라이드가 실제로 `tf2_echo base_link camera_link`에 정확히 반영되는지(Translation z=0.120, RPY pitch=0.150rad=8.594° 정확히 일치) — 둘 다 확인.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-12 세션 (계속) — 순수 로직 유닛 테스트 추가

이 프로젝트에 지금까지 실제 로직 테스트가 하나도 없었음(각 패키지 `package.xml`에 `python3-pytest` 등이 test_depend로는 있었지만 ament 코드 스타일 검사용이었고, 실제 계산 로직을 검증하는 테스트 파일 자체가 없었음). 하드웨어 없이 원격으로 할 수 있는 작업 중 하나로 판단해서 추가.

**환경 확인**: 이 Mac(Apple Silicon)엔 `cv2`/`numpy`는 있지만 `pyrealsense2`(pip 배포가 x86_64 Linux/Windows 위주라 arm64 macOS 미지원)와 `rclpy`(ROS2 미설치)는 없음 — 그래서 테스트 대상을 이 제약에 맞춰 나눠서 진행:
- **이 Mac에서 바로 실행 가능**: 데이터셋 변환 스크립트 3개(`convert_deepcrack_to_yolo_seg.py`/`convert_dacl10k_to_yolo_seg.py`/`convert_uavpdd_to_yolo_seg.py`)의 순수 함수 — cv2/numpy/표준 라이브러리만 필요.
- **젯슨에서만 실행 가능**: `vision_ai/measurement.py` — `pyrealsense2.rs2_deproject_pixel_to_point`에 의존.
- **rclpy 없이는 임포트 자체가 안 됨**: `lidar_mapping/coverage_grid_node.py`는 모듈 최상단에서 `import rclpy`를 하고 있어서, 셀 계산 로직이 그 안에 인라인돼 있으면 이 Mac에서 테스트 불가능.

**리팩터링**: `coverage_grid_node.py`의 순수 계산 부분(`position_to_cell()`, `build_status_payload()`)을 rclpy에 의존하지 않는 새 모듈 `lidar_mapping/coverage_math.py`로 분리 — `vision_ai/measurement.py`가 이미 쓰고 있던 것과 같은 패턴(ROS I/O는 노드 파일에, 계산은 별도 순수 모듈에). 노드 파일은 이 함수들을 import해서 쓰도록만 변경, 로직 자체는 안 바꿈.

**작성한 테스트(총 36개, 전부 통과)**:
- `scripts/test/test_convert_deepcrack.py`(6개) — 마스크→폴리곤 변환, 노이즈 필터링(`MIN_CONTOUR_AREA`), 파일 없음/빈 마스크 처리
- `scripts/test/test_convert_dacl10k.py`(5개) — Crack 클래스만 추출, 다른 18개 클래스(Rust 등) 제외, 3점 미만 폴리곤 스킵
- `scripts/test/test_convert_uavpdd.py`(5개) — 4개 크랙 서브타입 유지, Pothole/Repair 제외, bbox→4점 폴리곤 변환
- `src/lidar_mapping/test/test_coverage_math.py`(7개) — 셀 인덱스 계산(양수/음수/경계값), 2026-08-08 세션에서 젯슨 실측으로 확인했던 값과 동일한 결과 재현
- `src/vision_ai/test/test_measurement.py`(6개, 젯슨 전용) — 핀홀 공식 검증(65px→100mm), 0-depth 예외 처리, 2026-07-13 우드락 실측(1.4m, 55mm)과 같은 자릿수 합성 케이스로 회귀 확인

**검증**: 이 Mac에서 23개(변환 스크립트+coverage_math), 젯슨에서 13개(measurement+coverage_math 재확인) 전부 통과. `coverage_grid_node.py` 리팩터링 후 실제 노드 동작도 합성 TF로 재확인(칸 (1,2), 면적 2.2㎡ — 2026-08-08 세션과 동일한 결과, 회귀 없음).

## 2026-08-13 세션 — 학교에서 첫 실물 핸드헬드 테스트 (비행 없음, 카메라만 손으로 이동)

사용자가 학교에 도착해서 처음으로 실제 하드웨어(젯슨+D455F) 앞에서 직접 테스트 가능해짐 — 단, **드론은 띄우지 않고 카메라를 손으로 들고 이동**하는 조건. 지금까지 원격으로만 검증하던 여러 항목(라이브 SLAM, mm 측정, 3D 재구성)을 처음으로 실물로 확인.

**작업 관리 실수와 교훈 — 프로세스 중복으로 메모리 거의 소진**: 파이프라인을 여러 번 재시작하면서 `pkill -f "ros2 launch|realsense2_camera_node|rgbd_odometry|rtabmap"` 패턴만 썼는데, 이게 `vision_ai_node`/`recorder_node`/`drone_core_node`/`lidar_mapping_node`/`crack_fusion_node`/`coverage_grid_node`/`web_dashboard_node`/`static_transform_publisher`는 전혀 안 잡아서 재시작할 때마다 이 노드들이 그대로 남고 새 세대가 그 위에 또 쌓임. 3~5세대가 겹쳐 쌓이면서 가용 메모리 85Mi, 스왑 70%까지 찍음(2026-07-12 OOM 인시던트와 같은 패턴). `pkill -f "bridge_drone_ws/install|ros2 launch|realsense2_camera_node|rgbd_odometry|rtabmap|static_transform_publisher"`로 패턴을 넓혀서 해결. **교훈**: 앞으로 파이프라인을 재시작할 때는 반드시 `ps aux`로 전체 프로세스 목록을 확인해서 "노드마다 정확히 1개"인지 검증한 뒤 진행할 것 — 특히 `static_transform_publisher`처럼 노드 이름과 실행 파일명이 다른 경우 놓치기 쉬움.

**RTAB-Map 라이브 SLAM 검증 — 처음으로 성공**: 카메라를 실제로 든 채 좌우로 이동시켜봤지만 처음엔 `Odom: quality=0`이 계속 반복(추정 실패, `Not enough inliers 0/15` 반복). 순서대로 원인 규명:
1. **가설(기각)**: `depth_module.depth_profile`(1280x720)과 `rgb_camera.color_profile`(1280x800)의 종횡비가 달라서 `align_depth` 재투영 시 프레임 대부분이 무효(depth=0)가 되는 줄 알았음 — 실측해보니 depth 유효 픽셀 비율이 해상도를 맞춰도(1280x720x30 동일) 16.7%→16.8%로 거의 그대로라 기각. (그래도 두 스트림을 맞추는 게 더 단순하다고 판단해 `launch/bridge_drone.launch.py`의 `rgb_camera.color_profile`은 `1280x720x30`으로 유지.)
2. **진짜 원인**: `config/rtabmap_tuning.yaml`의 `Vis/MinInliers`를 지난 세션에 20→15로 완화해뒀는데, 실제 사무실 환경(창문 없는 실내, 어질러진 책상 등)에서는 그마저도 너무 엄격해서 매 프레임 등록 실패 — 로그에 가끔 inlier가 6~10개까지 올라가는 걸 보고 **15→8로 재조정**하자 즉시 `Odom: quality=100~540`대로 정상 트래킹 시작.
3. **TF 체인 실시간 확인**: `tf2_echo odom base_link`/`tf2_echo map odom` 둘 다 프레임마다 Translation/Rotation이 실제 움직임에 맞춰 갱신되는 것 확인 — 지금까지 미검증이던 "실제 이동 중 TF 갱신" 항목이 드디어 해소됨.
4. **루프클로저**: 후보는 감지되지만(`Rejecting all added loop closures... graph error ratio 4.8~9.7`), `RGBD/OptimizeMaxError`(기본 3.0 표준편차) 초과로 계속 거부됨 — 짧은 핸드헬드 이동이라 오도메트리 드리프트가 누적된 정황, 안전장치 자체는 정상 동작(잘못된 루프클로저로 맵이 깨지는 걸 막음).
5. **새로 발견한 버그 — 오도메트리 guess 발산**: 카메라를 가만히 둔 채로 등록이 계속 실패하자, 내부 모션 예측(guess)이 매 프레임 같은 방향으로 계속 외삽되다가 `xyz=488, -21, 1037`(미터!)까지 발산 — 이후로는 실제로 다시 움직여도 guess 자체가 완전히 틀어져서 "All projected points are outside the camera"만 반복하며 영원히 복구 불가능해짐. `Odom/ResetCountdown: "1"`을 추가해서 연속 등록 실패 시 오도메트리가 스스로 리셋되도록 함(수동 재시작 없이 자가 복구).

**`vision_ai` 측정 파이프라인 — 카메라 리팩터링 후 첫 실물 검증**:
- vision_ai 자체는 정상 발행 확인(`/vision_ai/detections` ~9Hz).
- **크랙 모델 도메인 시프트 발견**: 예전 우드락 실험(2026-07-13)에 쓰던 흰색 스티로폼 긁힘 자국을 다시 대봤는데 `crack_seg_v3`(DeepCrack+dacl10k 실제 콘크리트 균열로만 파인튜닝)가 전혀 탐지 못함 — confidence를 0.01까지 낮춰도 최고값이 0.0275(기본 임계값 0.25의 1/10)로, 임계값 문제가 아니라 모델이 이 저대비 합성 결함 패턴 자체를 학습한 적이 없어서 못 알아보는 것으로 확인. **모델이 실제 균열 도메인에 특화된 결과일 가능성**(나쁜 신호가 아닐 수 있음) — 다만 예전 검증 방법(우드락 대체물)이 지금 모델 버전엔 더 이상 안 맞는다는 뜻이라, 실물 균열 없이 정확도 재검증할 방법이 마땅치 않아짐.
- **실제 벽 틈(폭 2cm, 깊이 1cm, 새로 1m, 거리 1.5m)으로 대체 테스트**: 탐지는 잘 됨(confidence 0.29~0.36, class="crack") — 실제 결함 형태에는 반응한다는 뜻. 하지만 `length_mm`/`width_mm`이 계속 `null`.
- **측정 실패 원인 규명 + 버그 수정**: bbox 4개 모서리 중점 중 3개가 정확히 depth=0(무효)이었음. `src/vision_ai/vision_ai/measurement.py`에 `_nearest_valid_depth()` 추가 — 측정 지점이 무효면 반경 5px까지 링 단위로 넓혀가며 가장 가까운 유효 depth를 대신 사용(`deproject_point_m`/`measure_distance_mm` 둘 다 적용). 유닛 테스트도 갱신: 기존 "단일 무효 픽셀→예외" 테스트를 실제로는 폴백으로 복구되는 게 맞는 동작이라 판단해 "반경 내 유효 depth 전혀 없음→예외"로 교체하고, "단일 무효 픽셀→폴백으로 복구" 테스트를 새로 추가(총 7개, 전부 통과).
- **그래도 이 벽 틈은 여전히 측정 실패**: 반경 8px(17×17 영역)까지 넓혀서 확인해봐도 한쪽 모서리 지점은 유효 depth가 단 하나도 없음 — 틈의 한쪽 면이 카메라에서 볼 때 그늘지거나 안쪽으로 깊어서 스테레오 depth 자체가 그 구역을 못 읽는 **실제 물리적 한계**로 판단(반경을 억지로 더 넓히면 결함과 무관한 배경 depth를 가져다 써서 오히려 부정확해짐). **콘크리트 표면의 얕은 선형 균열은 이렇게 깊은 틈보다 훨씬 유리한 조건일 가능성이 높음** — 실제 균열로 재검증 필요, 다음 우선순위로 기록.

**실시간 3D 맵(dense reconstruction) — 새로운 목표, 부분 성공**: 사용자가 "균열보다 먼저 실시간으로 물체/구조물을 depth 포함해서 3D로 쌓는 것" 자체를 검증하고 싶다고 요청. RTAB-Map이 이미 `/cloud_map`(컬러 포인트클라우드), `/map`/`/grid_prob_map`(2D occupancy), `/octomap_full`(3D 복셀) 토픽을 광고하고 있었지만 전부 실제로는 발행되지 않고 있었음 — `map_always_update`(기본 false, 그래프가 크게 갱신될 때만 맵 토픽 발행) 때문으로 추정, 지금까지 루프클로저가 계속 거부돼서 "크게 갱신"되는 이벤트 자체가 없었던 것으로 보임. `config/rtabmap_tuning.yaml`에 `map_always_update: true` 추가해서 시도했다가 **첫 시도에서 `InvalidParameterTypeException`으로 `rtabmap` 노드가 즉시 죽는 사고**(exit code -6) — RTAB-Map의 내부 Parameters(전부 문자열, `Vis/MinInliers: "8"`처럼 따옴표 필요)와 달리 `map_always_update`는 ROS2 네이티브 bool 파라미터라 문자열 `"true"`를 주면 타입 불일치로 죽는다는 걸 실측으로 확인. YAML에서 따옴표 없이 `true`(진짜 bool)로 수정해서 해결. **결과**: `/map`, `/grid_prob_map`, `/octomap_full` 전부 ~1Hz로 실시간 발행 확인(수정 전엔 `Maps update=0.0000s`이던 게 수정 후 `0.03~0.04s`로 실제 연산이 도는 것도 로그로 확인). **단, 컬러 포인트클라우드 `/cloud_map`만은 여전히 안 나옴** — `RGBD/CreateOccupancyGrid`/`Grid/3D`/`cloud_output_voxelized` 등 관련 파라미터는 전부 정상값인데도 원인 미상, 다음 세션 이어서 조사 필요. `/octomap_full`(3D 복셀, 색 없음)까지는 확인됐지만 사용자가 원래 그렸던 "실제 다리처럼 보이는" 결과물엔 `/cloud_map`(색 있는 점구름)이 필요.

**향후 방향(설계만, 아직 미구현) — 균열 탐지를 3D 재구성 이후로 미루는 2단계 구조**: 사용자 요청으로 논의만 진행. 실시간 파트는 지금처럼 프레임별 2D 탐지(조종사 즉석 피드백용)로 유지하고, 정밀 균열 측정은 비행/촬영이 끝난 뒤 오프라인으로 수행하는 2단계 구조로 가는 방향에 합의. 두 가지 구현 후보:
- **(A) 관측 병합**: 같은 물리적 균열을 여러 각도에서 반복 관측한 것들을 map 좌표 기준으로 묶어서 유효한 depth 측정치의 중앙값을 취함 — 오늘 만든 `_nearest_valid_depth` 폴백의 확장판, 기존 코드 재사용 위주라 구현이 가벼움.
- **(B) 3D 메쉬 직접 탐지**: `reconstruct_from_flight.sh`가 만드는 텍스처 입힌 메쉬(여러 프레임의 depth를 이미 합쳐놓은 결과물)의 텍스처 이미지에 YOLO를 돌리고, UV 매핑으로 텍스처 픽셀을 메쉬의 3D 정점에 역매핑해서 실제 표면 위 좌표로 측정 — 원래 사용자가 그렸던 "3D 다리 구조 위에 균열이 실제로 표시" 그림에 가장 가까움, 텍스처↔메쉬 매핑 코드를 새로 짜야 해서 작업량이 더 큼.
아직 착수 전 — 지금은 `/cloud_map` 라이브 발행 문제 해결이 선행 과제.

전부 GitHub에 커밋 예정(이 세션 종료 시).

`README.md`에 테스트 실행 방법 추가. 전부 GitHub에 커밋/푸시 완료.

## 2026-08-19 세션 — depth_coverage_node 신규 구현, RTAB-Map 조각화 문제 발견, mm 측정 재검증, D455F 셀프캘리브레이션 시도

목표: 사용자가 학교에서 실물 하드웨어로 "실시간 3D 재구성"을 처음부터 검증하고 싶어함 — 콘크리트/균열은 일단 제쳐두고, 작은 물체(연필꽂이)로 파이프라인 자체가 도는지부터 확인하자는 방향으로 진행.

**`/cloud_map` 미발행 — 재확인 결과 버그 아니었음**: 카메라가 몇 분간 정지 상태일 때 `/cloud_map`이 전혀 안 나왔는데, `(local map=1, WM=1)` 로그로 확인해보니 RTAB-Map 지도(Working Memory)에 새 노드가 전혀 안 늘고 있었음 — `/cloud_map`은 "그래프가 실제로 바뀔 때"(`Graph has changed!`)만 재생성되는 구조라 지도가 안 바뀌면 재생성될 일도 없는 게 정상 동작. 실제로 카메라를 손으로 움직이자 즉시 발행 시작(~0.4~0.5Hz), WM도 1→50까지 증가 확인.

**RTAB-Map DB 조각화 발견(신규 실측 문제)**: 연필꽂이를 손으로 한 바퀴 돌려 촬영 후 `scripts/reconstruct_from_flight.sh`로 재구성했더니 `rtabmap-export`가 `poses=1, links=0`이라는 이상한 결과를 냄. `rtabmap.db`를 Python `sqlite3` 모듈로 직접 열어 `Node`/`Link` 테이블 조회 — 총 노드 749개가 **8개의 서로 다른 map_id(0~7)로 쪼개져 있었음**(369/1/20/322/9/1/6/21개). 세션 중 오도메트리가 **9번 리셋**됐는데(`Odometry is reset ... Increment map id!`), 리셋마다 좌표 원점이 새로 잡히고 이후 조각이 이전 조각과 루프클로저로 다시 안 이어짐(`Rejected loop closure ... Not enough inliers`). `poses=1`은 대부분의 조각이 그래프상 고립돼서 최적화 대상에서 빠졌기 때문으로 추정. 포인트클라우드를 다운받아 좌표 기반 voxel 연결요소 클러스터링(map_id별 PointSourceId는 `--cam_projection`이 PDAL 미설치로 못 씀, `rtabmap-export --cam_projection`이 "PDAL support 없음" 경고와 함께 카메라ID 생략)으로 111개 클러스터(최대 덩어리 9,735점=58%, 나머지는 흩어짐) 확인, 아티팩트로 조각별 색상 뷰어를 만들어 직접 눈으로도 확인. **교훈**: 카메라를 중간에 멈추거나 다시 잡으면 리셋이 나고 그때마다 지도가 갈라짐 — 다음엔 처음부터 끝까지 끊김 없이 한 번에 움직이는 게 중요. 이번엔 젯슨이 유선 연결이라 자유롭게 재시도가 어려워 다음 하드웨어 세션으로 이월.

**단일 프레임 "2.5D" 캡처로 우회**: SLAM 없이 depth 프레임 한 장만으로 픽셀별 3D 역투영(`rs2_deproject_pixel_to_point`)해서 점구름을 만드는 방식 — 조각날 일이 없는 대신 카메라가 본 한 면만 나옴(뒷면은 데이터 없음, 완전한 3D엔 여러 각도 필요하다는 걸 직접 보여주는 지점). `capture_single_frame.py`(신규, pyrealsense2 단독 스크립트, ROS 파이프라인과 무관하게 동작)로 5m 범위까지 캡처(153,834점). RANSAC 평면검출(최대 평면=바닥으로 추정)+voxel 클러스터링으로 바닥/물체/배경을 분리하고 카메라 기준 거리(평균/최소/최대)까지 계산, 카테고리별 켜고 끄는 토글이 있는 뷰어로 확인 — 물체(가장 가까운 덩어리) 평균 1.21m, 바닥 평균 1.50m로 실측과 정성적으로 부합. 다만 완벽한 경계 분리는 아니고 물체가 바닥/책상면과 맞닿으면 같은 덩어리로 합쳐질 수 있음(참고용 눈대중 수준).

**`depth_coverage_node` 신규 구현**: `src/vision_ai/vision_ai/depth_coverage_node.py` — color/depth 동기화해서 depth 무효(0) 픽셀을 반투명 빨간색으로 덮어 그려 `/vision_ai/depth_coverage`로 발행(YOLO 추론과 무관한 독립 노드, 장애 격리 원칙 유지). `web_dashboard`에 두 번째 카메라 뷰로 연동 — 바이너리 웹소켓 채널에 1바이트 타입 태그(`A`=YOLO 주석, `D`=depth 커버리지)를 붙여서 프론트엔드가 구분하도록 `index.html`도 수정. **실측**: 물체 테두리(실루엣 경계)에서만 얇게 빨간 무효 영역이 나오고 표면 안쪽은 깨끗함 — 스테레오 depth 카메라의 전형적인 실루엣 경계 아티팩트(좌우 IR 카메라가 경계에서 서로 다른 걸 봐서 매칭 실패)로, 8/13 벽 틈 depth 무효 문제와 같은 계열. 균열처럼 얕은 선형 결함엔 영향이 적을 것으로 예상(표면 자체는 깨끗하므로).

**vision_ai mm 측정 정확도 재검증 완료 — 8/7 카메라 리팩터링 이후 최초 실물 검증**: 60cm 자를 세우고 실제 ROS 파이프라인(`realsense2_camera_node`+`vision_ai_node`)이 발행하는 color+depth 프레임을 캡처(`capture_ros_frame.py` 신규, message_filters 동기화 1회성 구독 노드)해서 자의 빨간 10cm 눈금 두 지점을 측정. 자에 인쇄된 숫자 자체는 1m/76cm 거리에서 자가 프레임 폭의 50px밖에 안 차지해서 카메라 해상도로는 전혀 안 읽혀서(1mm≈1.76px), 빨간 눈금의 색상을 프로그램적으로 검출해서 대체. 첫 시도는 "가장 빨간 픽셀"의 x좌표를 그대로 썼다가 얇은 자 몸체를 벗어나 depth=0(무효)이 나옴 — depth가 실제로 유효한 연속 구간(700~900mm대)을 찾아 그 구간의 median x/depth로 재선정해서 해결(얇은 물체는 픽셀 하나 단위로 유효/무효가 갈릴 수 있다는 교훈, `_nearest_valid_depth`와 같은 계열의 함정). **측정값 107.0mm vs 실제 100mm — 오차 +7.0mm(7.0%)**, 카메라~자 거리 약 76~78cm. 7/13 우드락 실험(1.4m에서 7.5% 오차)과 오차율이 거의 동일 — **8/7 카메라 캡처 단일화 리팩터링이 측정 정확도를 깨지 않았다는 게 최초로 실물 확인됨**.

**D455F 셀프캘리브레이션(On-Chip + Tare) 시도**: 위 7% 오차를 줄여보려고 Intel 공식 예제(`~/librealsense/wrappers/python/examples/depth_auto_calibration_example.py`, 소스에 이미 포함돼 있었음)를 참고해 `pyrealsense2.auto_calibrated_device` API로 시도.
- **On-Chip calibration(wall mode) 성공**: 공식 예제는 캘리브레이션 전체에서 emitter를 끄는데, 텍스처 없는 벽이 타겟이라 그대로 하면 "Not enough depth pixels! - low fill factor" 에러가 남 — emitter를 켜고 재시도해서 성공, health=-0.0108(거의 보정 불필요한 수준)로 온칩 보정값 갱신 및 저장(`write_calibration()`) 완료.
- **Tare calibration 실패, 미해결**: 벽까지 정확히 1m(줄자 확인)를 ground truth로 `run_tare_calibration(1000.0, ...)` 호출 시 매번 `hwmon command 0x80(...) failed (response -7= HW not ready)`. JSON 파라미터를 공식 unit test 기본값(`unit-tests/live/calib/pytest-tare-calibrations.py`)으로 바꿔도, `hardware_reset()` API 호출 후 15초 대기해도, **USB 케이블을 물리적으로 뽑았다 다시 꽂은 뒤에도(재열거 확인됨, `lsusb`로 새 Device 번호 확인)** 동일하게 재현됨 — 코드/파라미터/일시적 상태 문제가 아니라 이 카메라(펌웨어 5.15.1.55)의 실제 제약이나 버그로 추정. **다음에 시도할 것**: 펌웨어 업데이트 확인, 또는 Intel 공식 포럼에 D455F+이 펌웨어 조합의 Tare 이슈 문의. 참고로 On-Chip 보정의 health 값이 이미 거의 0에 가까웠던 걸 보면, 애초에 7% 오차의 원인이 광학 캘리브레이션(intrinsic/extrinsic) 쪽이 아니라 depth 스케일 자체의 문제(Tare가 고치는 대상)이거나, 혹은 우리 쪽 픽셀 선정/측정 방법론의 잔차일 가능성도 있음 — 아직 원인 확정은 아님.

전부 GitHub에 커밋/푸시 완료.

## 2026-08-20 세션 — Odom/Strategy 설정 오류 발견, 촬영/처리 분리 워크플로 도입, 지도 조각화 해결 + 첫 루프클로저 성공

목표: 사용자 요청으로 "동아리방 벽 한 면을 구간별로 나눠 촬영해서 하나로 합치기" — 넓은 평면을 나눠 스캔해 병합하는, 실제 교량 하부 스캔과 가장 가까운 시나리오.

**① `Odom/Strategy` 값 의미가 우리 문서와 정반대였음(중대한 설정 오류, 2026-08-12부터 잠복)**

8/19 조각화의 원인을 찾다가 `Odom/ResetCountdown`을 의심해서 파라미터 의미를 다시 확인하던 중 발견. 설치된 라이브러리에 직접 물어본 결과(`rtabmap-export --params`):
```
Param: Odom/Strategy = "0"   [0=Frame-to-Map (F2M) 1=Frame-to-Frame (F2F) ...]
```
그런데 `config/rtabmap_tuning.yaml`엔 8/12에 "기본 0=F2F를 1=F2M으로 바꿈"이라고 주석을 달고 `"1"`로 설정해뒀음 — **정확히 반대**. 즉 기본값(0)이 이미 F2M(강건한 쪽)이었는데 우리가 F2F(약한 쪽)로 바꿔놓고 두 달 가까이 그 상태로 돌리고 있었음. 8/13 라이브 테스트에서 트래킹이 유독 불안해 `Vis/MinInliers`를 20→15→8까지 낮춰야 했던 것도 이것 때문일 가능성이 큼. `OdomF2M/MaxSize: 3000`도 F2M이 꺼져 있었으니 아무 효과가 없었음.

**왜 8/12에 잘못 기록됐나 / 재발 방지**: 그때 세션 기록을 보면 "젯슨에 노드를 띄우고 `ros2 param list/describe/get`으로 직접 확인"했다고 돼 있는데, 이번에 확인해보니 **`ros2 param describe`는 RTAB-Map 파라미터의 설명 필드를 비워서 반환**함(타입/제약만 나옴 — ROS 래퍼가 description을 안 채움). 즉 그때 노드에서 검증한 건 *이름과 기본값*뿐이었고 값의 *의미*는 웹 문서에 의존했는데 거기서 0/1이 뒤집힌 채로 옮겨진 것. **앞으로 RTAB-Map 파라미터의 의미까지 확인할 땐 `rtabmap-export --params | grep -i <이름>`을 쓸 것**(GUI `rtabmap --params`는 헤드리스 젯슨에서 Qt 플러그인 에러로 실패). 이 교훈을 `config/rtabmap_tuning.yaml` 헤더 주석에도 남김.

**② `Odom/ResetCountdown` 1 → 10**

공식 설명 확인: *"...odometry resumes from the last successfully computed pose with large covariance **to trigger a new map**."* — 리셋이 곧 새 지도(map_id) 생성이라는 게 문서로 확인됨. 8/13에 "guess 488m 발산" 자동복구용으로 넣은 값 `1`은 **단 한 프레임만 등록에 실패해도 즉시 지도를 갈라버리는** 설정이었고, 이게 8/19 연필꽂이 스캔에서 9번 리셋 → 8개 조각이 난 직접 원인. 10으로 올려서 순간적 끊김은 견디되 진짜 발산은 여전히 자동복구되게 함.

**③ 촬영과 처리를 분리하는 워크플로 신규 도입 (사용자 아이디어)**

사용자가 "리셋 위험 안 생기게 찍은 사진들 후처리 하면 안 되냐"고 제안 — 로그를 보니 근거가 명확했음. `rgbd_odometry`의 프레임당 처리 시간이 0.14~0.22s인데 카메라는 그보다 빠르게 밀어넣어서 **실시간 모드에서는 프레임을 대량으로 버리고 있었음**(`Dropping image/scan data` 경고 다수). 버려진 만큼 연속 프레임 사이 움직임이 커져 정합이 실패 → 리셋 → 조각화로 이어지는 연쇄였음.

- `scripts/capture_bag.sh` 신규 — 카메라만 띄우고 원본 프레임을 rosbag2로 녹화(`start`/`stop` 서브커맨드). SLAM/YOLO를 안 띄워 CPU를 비워둠.
- `launch/replay_slam.launch.py` 신규 — 재생 전용 SLAM 스택(rgbd_odometry+rtabmap만, `use_sim_time:=true`, `always_process_most_recent_frame:=false`). 후자는 실시간 로그가 프레임을 버릴 때마다 직접 추천하던 파라미터.
- `scripts/replay_slam.sh` 신규 — bag을 느린 속도로 재생하며 위 스택을 돌려 `~/.ros/rtabmap.db` 생성.
- 부가 이득: **같은 데이터로 파라미터만 바꿔 몇 번이고 재시도 가능** — 촬영을 다시 안 해도 됨.

**저장 매체 병목 실측**: `dd`로 재보니 젯슨 microSD 순차 쓰기가 **25.3MB/s**. 1280x720x30 원본은 약 138MB/s라 물리적으로 녹화 불가. `848x480x15` + rosbag2 zstd 메시지 압축으로 **약 17MB/s**가 되어 한계 안에 들어옴(20초 테스트 321MB, 드롭 0). `compressed_image_transport` 플러그인은 미설치 상태(설치하면 더 여유가 생기지만 캠퍼스망 apt 이슈 감수 필요).
**해상도 트레이드오프(사용자가 지적)**: fx=646(1280 기준) 실측값으로 계산하면 1m 거리에서 픽셀당 실제 크기가 1280x720은 1.55mm/px, 848x480은 2.34mm/px — 측정 가능한 최소 결함이 대략 3~5mm → 5~7mm로 나빠짐. 다만 **풀 해상도로도 0.3mm급 미세 균열은 애초에 측정 불가**(1픽셀에도 못 미침, docs 8번 항목 1의 GSD 우려와 동일)라 "되던 게 안 되는" 수준의 손실은 아님. 근본 해결은 USB 3.0 SSD를 달아 저장 병목을 없애는 것(docs 8번 항목 8과 직결).

**④ 결과 — 벽 스캔 성공, 지도 조각화 해결 + 첫 루프클로저**

동아리방 벽을 지그재그로 훑으며 102.8초 녹화(컬러 1541프레임 = 15fps×102.8s, **촬영 중 드롭 사실상 0**, 1.7GB). 0.25배속으로 재생하며 SLAM(약 7분 소요).

| 항목 | 8/19 라이브 | 8/20 오프라인 재생 |
|---|---|---|
| 지도 조각(map_id) | 8개 | **1개** |
| 루프클로저 성공 | 0개(전부 거부) | **70개** |
| 오도메트리 리셋 | 9회 | **0회** |
| 프레임 드롭 | 다수 | **0** |
| Odom quality | 0~540 | **666~718** |

DB 직접 조회(`Node`/`Link` 테이블): 노드 99개 전부 `map_id 0`, 링크 156개(이웃 80 / 루프클로저 70 / 로컬공간 6), 궤적 범위 1.18×3.24×2.25m, 누적 이동 15.55m. **7월부터 한 번도 성공한 적 없던 루프클로저가 처음으로 대량 성공** — 지도가 하나로 단단히 묶였다는 뜻.

`scripts/reconstruct_from_flight.sh`로 재구성: 포인트클라우드 **522,945점**(16MB), 텍스처 메쉬 250,487 폴리곤/147,671 정점, 포즈 41개(8/19엔 `poses=1`로 실패했던 그 단계). WebGL 뷰어 아티팩트로 실제 확인 — 방 형태와 스캔 궤적이 알아볼 수 있게 나옴.

**남은 것**: TF 경고(`camera_color_optical_frame does not exist`)가 재생 초반에 5번 나고 멈춤 — bag의 `/tf_static`과 첫 프레임 사이 도착 순서 경합으로 보이며 무해하지만, 정밀하게 하려면 재생 시작 전 static TF를 먼저 세우는 방식으로 다듬을 여지 있음.

**⑤ 고스팅(같은 표면이 여러 겹으로 어긋나 쌓임) 정량화 및 해결**

사용자가 뷰어를 보고 "같은 물체가 3번씩 약간 겹쳐 보인다"고 지적 — 감이 아니라 수치로 확인하려고 측정 스크립트를 씀(가장 큰 평면을 RANSAC으로 찾고, 그 평면까지의 부호 있는 거리 히스토그램을 봄. 정합이 완벽하면 봉우리 1개, 고스팅이 있으면 여러 개).

**측정 결과 — 사용자 지적이 맞았음**: 봉우리가 **2개**(-25mm, +1mm)로 갈렸고 **간격 26mm**, 평면 두께 σ=29.3mm. 센서 노이즈만이면 단봉 정규분포여야 하므로, 같은 벽이 2.6cm 어긋난 채 두 겹으로 쌓였다는 뜻.

**해결 — 전역 번들 조정(`rtabmap-export --ba`)**: 재촬영/재생 없이 export만 다시 하면 됨. 결과 **봉우리 2개 → 1개**, σ **29.3mm → 20.7mm**. 겹쳐 보이던 두 겹이 하나로 병합됨. 앞으로 재구성 시 `--ba`를 기본으로 붙일 것.

**선명도(밀도) 문제 — `rtabmap-export` 기본값이 원인**: 사용자가 "사진처럼 선명하진 않고 뭉개진다"고 해서 확인해보니 기본값이 `--decimation 4`(depth 이미지를 4배 축소한 뒤 점 생성)에 `--voxel 0.01`(1cm 격자로 병합). 즉 848×480으로 찍은 걸 **212×120으로 줄여서** 점을 만들고 있었음. `--decimation 1 --voxel 0.004`로 재추출하니 **49만 → 711만 점**(14배). 다만 웹으로 통째로 보기엔 너무 커서 뷰어에는 축소본을 씀.
**중요한 구분**: 밀도를 올려도 점구름은 원리적으로 사진만큼 선명해질 수 없음 — 점 하나하나가 depth 노이즈(σ 20.7mm)만큼 흔들린 위치에 찍히므로 그보다 작은 디테일은 노이즈에 묻힘. "사진처럼 보이는" 결과물은 텍스처 메쉬 쪽(`--mesh --texture`, 실제 촬영 사진을 표면에 입힘)이고, **텍스처의 선명함과 형상의 정확도는 별개**라는 점을 사용자에게 명시함(8/9에 컨셉 시각화로 과신했다가 정정했던 것과 같은 지점).

**⑥ ICP 정합 시도 → 실패, 되돌림 (중요한 음성 결과)**

남은 20.7mm를 더 줄이려고 ICP 기반 정합을 시도. `Reg/Strategy: 0(Vis) → 2(VisIcp)`, `RGBD/NeighborLinkRefining: false → true`, `Icp/VoxelSize: 0.05 → 0.02`.

**결과: 지도가 아예 안 만들어짐.** rtabmap이 27번 반복을 도는 동안 WM(working memory)이 **1에 고정** — 노드가 하나도 추가되지 않음. 오도메트리는 정상이었음(quality 579~599, `rgbd_odometry`는 `icpParams_=0`이라 애초에 ICP를 쓰지 않음). 즉 오도메트리가 아니라 rtabmap의 링크 등록 단계가 막힌 것.

**범인 격리**: `RGBD/NeighborLinkRefining`만 false로 되돌려 재실험(전체 7분 대신 `timeout`으로 40초 분량만 재생하는 짧은 A/B) → **결과 동일하게 WM=1 고정**. 따라서 **`Reg/Strategy=2` 자체가 원인**.

**추정 원인(미확증)**: 평평한 벽 한 면은 ICP의 전형적인 퇴화(degenerate) 조건 — 평면을 따라 미끄러져도 점-평면 오차가 줄지 않아 변환이 확정되지 않음. **사실이라면 콘크리트 교량 하부에서도 똑같이 실패**한다는 뜻이라, 이 프로젝트에서는 ICP 계열 정합을 기본 후보에서 빼는 게 맞다고 판단. 세 파라미터 모두 제거하고 기본값(Vis)으로 복원, 실험 기록은 `config/rtabmap_tuning.yaml` 주석에 남겨 재시도를 막음. 지도 DB도 실험 전 백업(`~/.ros/rtabmap_vis_only.db`)에서 복원해 노드 99개/조각 1개/루프클로저 70개 상태 확인.

**부수적으로 배운 것**: 이 버전 rosbag2에는 `--playback-duration` 옵션이 없음(옵션명 오류로 재생이 즉시 실패했는데 출력을 `/dev/null`로 버려서 원인 파악이 늦어짐). 짧게 잘라 재생하려면 `timeout <초> ros2 bag play ...`를 쓸 것. **원격 실험에서 출력을 버리지 말 것**도 교훈.

**이번 세션의 워크플로 이득이 실증된 지점**: 위 ICP 실험 전체가 **재촬영 없이** 같은 bag을 다시 돌리는 것만으로 진행됐고, 실패로 끝난 뒤에도 원래 결과를 백업 DB에서 그대로 되살릴 수 있었음.

## 2026-08-20 세션 (계속) — 오프라인 재생에 균열 탐지/태깅 연결 + 관측 병합(A안) 구현

지금까지 "탐지 → mm 측정 → 3D 지도 태깅"이 한 번에 이어지는 걸 실제로 본 적이 없었음(`crack_fusion_node`는 2026-08-07에 합성 TF로만 검증). 오늘 SLAM이 제대로 되기 시작해서 이제 가능해졌기에 연결함.

**`crack_collector_node` 신규 (`src/lidar_mapping/`)**: `crack_fusion_node`가 프레임마다 발행하는 `/crack_fusion/tagged_detections`는 "이 순간 보이는 크랙"이라 그대로 두면 스캔이 끝나는 순간 사라짐 — 지금까지 결과물이 파일로 남은 적이 없었음. 이 노드가 누적해서 **map 좌표 기준 15cm 반경으로 같은 균열의 반복 관측을 병합**하고, 크기는 **중앙값**으로 대표값을 뽑아 JSON으로 저장(기본 `~/.ros/cracks.json`, 5초마다 + 종료 시 원자적 교체로 기록). 이게 2026-08-13에 설계만 논의하고 미구현으로 남겨뒀던 **"관측 병합(A안)"**의 구현. 평균이 아니라 중앙값을 쓰는 이유는 depth 무효 프레임에서 나오는 튀는 값 때문(아래 검증에서 실증).

**`launch/replay_slam.launch.py` 확장**: `cracks:=true`(기본)면 `vision_ai_node` + `crack_fusion_node` + `crack_collector_node`가 SLAM과 함께 돌아감. `cracks:=false`로 끄면 YOLO 부하가 없어져 더 빠른 재생 속도를 쓸 수 있음. 출력 경로는 `cracks_output:=` 인자로 지정.

**1차 실행(벽 bag)**: 노드 3개 모두 정상 기동, 파일 생성까지 확인했지만 **탐지 0건** — 균열이 없는 벽이라 당연한 결과이나, 그 탓에 `crack_fusion → collector` 구간에 데이터가 흐르지 않아 검증이 안 된 채로 남음.

**합성 탐지 주입으로 구간 검증(2026-08-07에 쓴 방식 재사용)**: 재생 중 TF 체인이 살아있는 상태에서 `/vision_ai/detections`에 합성 탐지를 주입. **전부 기대값과 정확히 일치**:
- **TF 체인 생존 확인**: 재생 중 `tf2_echo map camera_color_optical_frame`이 실제 값 반환(translation `[0, -0.059, 0.050]`).
- **좌표 변환 정확**: 주입 `center_camera_m=[0.10, 0.05, 1.20]`(광학 프레임: x=우, y=하, z=전방) → `map_position_m=[1.2033, -0.1594, -0.0015]`. 기대값 x=1.20(전방), y=-0.10+(-0.059 TF오프셋)=-0.159, z=-0.05+0.05(카메라 높이)=0.00 과 소수점까지 일치.
- **병합 동작 확인**: 1.20m 지점 관측 6개 → 크랙 1개, 2.40m 지점 3개 → 별개의 크랙. 과병합도 과분할도 없음(반경 15cm가 이 스케일에 적절).
- **중앙값의 이상값 내성 실증**: 길이 샘플에 `52, 55, None, 300(이상값), 54, 53`을 섞었는데 결과 `length_mm_median: 54.0` — 평균이었으면 102.8mm로 크게 틀어졌을 값. `observations: 6` vs `length_samples: 5`로 **측정 실패 프레임 수까지 결과에 드러남**(depth 무효가 얼마나 섞였는지 사후에 알 수 있음).

**부수 수정**: 재생 스크립트가 SIGINT로 파이프라인을 정리하는 게 정상 종료 경로인데, `rclpy.spin()`이 그때 `ExternalShutdownException`을 던져 트레이스백 + exit code 1로 끝나 로그가 지저분했음 — `crack_collector_node`의 `main()`에서 `KeyboardInterrupt`와 함께 잡도록 수정(기존 노드들도 같은 패턴이라 나중에 정리 대상).

**아직 안 된 것**: 실제 균열로는 미검증. 위 검증은 전부 합성 탐지 기반이고, 벽 bag에는 균열이 없었음. **다음 단계는 진짜 균열이 있는 표면(캠퍼스 콘크리트 벽/보도블록/건물 외벽 등)을 이 워크플로로 촬영해서 탐지·측정·태깅이 실제로 나오는지 보는 것.**
