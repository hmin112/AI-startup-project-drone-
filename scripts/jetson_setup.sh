#!/usr/bin/env bash
# 젯슨 개발 환경 재구축 — docs/jetson_setup_log.md에 기록된 설치 과정과 그때
# 겪은 함정들을 그대로 스크립트로 굳힌 것.
#
# 왜 스크립트로 만들었나: 2026-09-09에 젯슨이 초기화되면서 2026-07-09부터 쌓아온
# 환경이 통째로 사라졌다. 로그 덕분에 복구는 가능했지만, 같은 일이 또 일어날 수
# 있으므로 이번엔 반복 가능한 형태로 남긴다.
#
# 모든 단계는 **여러 번 실행해도 안전**하다(이미 돼 있으면 건너뜀). 중간에 실패하면
# 그 단계만 다시 돌리면 된다.
#
# 사용법:
#   ./jetson_setup.sh              # 전체(순서대로)
#   ./jetson_setup.sh ros librealsense   # 특정 단계만
#   ./jetson_setup.sh --list       # 단계 목록
#
# 소요 시간: 전체 약 40~60분 (librealsense 빌드 10~15분, torch 설치가 큼)

set -uo pipefail

WS="${WS:-$HOME/bridge_drone_ws}"
CUDA_DIR=/usr/local/cuda-12.6
LOG_PREFIX="[setup]"

say()  { echo "$LOG_PREFIX $*"; }
warn() { echo "$LOG_PREFIX ⚠️  $*" >&2; }
die()  { echo "$LOG_PREFIX ❌ $*" >&2; exit 1; }

# sudo 실행 헬퍼.
# SSH로 비대화형 실행할 때는 tty가 없어서 plain `sudo`가 비밀번호를 받지 못하고
# "a terminal is required"로 죽는다. 미리 `sudo -v`로 캐시해두는 방법도 세션이
# 바뀌면 티켓이 공유되지 않아 실패한다.
#
# `echo "$SUDO_PASS" | sudo -S` 방식은 쓰면 안 된다 — **stdin을 덮어써서**
# 파이프로 입력을 받는 명령이 전부 깨진다. 실제로 이걸로 한 번 당했다:
#   echo "deb ..." | sudo tee /etc/apt/sources.list.d/ros2.list
# 에서 tee가 받아야 할 내용 대신 비밀번호가 stdin을 차지해 **빈 파일**이 만들어졌고,
# ROS 저장소가 등록되지 않아 "Unable to locate package ros-humble-ros-base"가 났다.
# librealsense의 udev 스크립트에 개행을 흘려넣는 트릭도 같은 이유로 깨진다.
#
# 그래서 stdin을 건드리지 않는 SUDO_ASKPASS(-A)를 쓴다.
#   SUDO_PASS=... ./jetson_setup.sh     # 원격 자동 실행
#   ./jetson_setup.sh                   # 콘솔에서 직접 (평소처럼 물어봄)
if [ -n "${SUDO_PASS:-}" ]; then
  _ASKPASS="$(mktemp)"
  printf '#!/bin/sh\nprintf "%%s\\n" "$SUDO_PASS_INNER"\n' > "$_ASKPASS"
  chmod 700 "$_ASKPASS"
  export SUDO_PASS_INNER="$SUDO_PASS"
  export SUDO_ASKPASS="$_ASKPASS"
  trap 'rm -f "$_ASKPASS"' EXIT INT TERM
fi

SUDO() {
  if [ -n "${SUDO_ASKPASS:-}" ]; then
    sudo -A "$@"
  else
    sudo "$@"
  fi
}

# 캠퍼스망 필터 때문에 apt가 간헐적으로 실패한다(아래 stage_apt_sources 참고).
# 그래서 apt는 항상 재시도로 감싼다.
apt_retry() {
  local tries=5 i=1
  while [ "$i" -le "$tries" ]; do
    if SUDO apt-get install -y "$@"; then return 0; fi
    warn "apt 실패 ($i/$tries) — 캠퍼스망 필터 의심, 재시도"
    sleep 5
    i=$((i + 1))
  done
  return 1
}

# 저장소 목록 갱신을 재시도한다. 설치(apt-get install)만 재시도하는 걸로는 부족한데,
# 캠퍼스망 필터가 가로채는 지점이 **install이 아니라 update**이기 때문이다.
# update가 실패하면 패키지 목록 자체가 없어서 install은 몇 번을 재시도해도
# "Unable to locate package"만 반복한다(2026-09-09에 실제로 이걸로 5번 헛돌았음).
#
# 성공 판정은 "명령이 0을 반환했는가"가 아니라 **원하는 패키지가 실제로 목록에
# 잡혔는가**로 한다 — apt-get update는 일부 저장소가 실패해도 0을 반환할 수 있다.
apt_update_retry() {
  local verify="$1" tries=8 i=1
  while [ "$i" -le "$tries" ]; do
    SUDO apt-get update > /tmp/apt_update.log 2>&1
    # 주의: `... | grep -q` 를 조건문에 쓰면 안 된다. grep -q는 첫 매치에서 즉시
    # 끝나면서 앞 명령에 SIGPIPE를 보내고, 이 스크립트의 `set -o pipefail` 때문에
    # **매치에 성공했는데도 파이프라인이 실패로 판정**된다. 2026-09-09에 이걸로
    # ROS 목록을 정상적으로 받아놓고도 8번 전부 실패 처리하며 헛돌았다.
    # 그래서 파이프를 쓰지 않고 변수에 담아 검사한다.
    local policy
    policy="$(LC_ALL=C apt-cache policy "$verify" 2>/dev/null)"
    case "$policy" in
      *"Candidate: "[0-9]*)
        say "  패키지 목록 확보 ($verify)"
        return 0 ;;
    esac
    warn "update 후에도 $verify 를 못 찾음 ($i/$tries) — 캠퍼스망 필터, 재시도"
    grep -iE 'NOSPLIT|Hash Sum|Failed to fetch' /tmp/apt_update.log | head -2
    sleep 5
    i=$((i + 1))
  done
  return 1
}

# --- 1. apt 소스: 캠퍼스망 콘텐츠 필터 우회 -----------------------------------
# 조선대 캠퍼스망의 필터링 장비가 평문 HTTP 다운로드를 간헐적으로 가로채
# 차단 페이지로 바꿔치기한다. apt에는 'Clearsigned file isn't valid, got NOSPLIT'
# 또는 'Hash Sum mismatch'로 나타난다. ports.ubuntu.com은 https로 바꾸면 해결되고,
# packages.ros.org는 인증서가 안 맞아 https로 못 바꾸므로 재시도로만 우회한다.
stage_apt_sources() {
  say "apt 소스를 https로 전환 (캠퍼스망 필터 우회)"
  local changed=0
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [ -f "$f" ] || continue
    if grep -q 'http://ports.ubuntu.com' "$f" 2>/dev/null; then
      SUDO sed -i 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g' "$f"
      say "  $f 수정"
      changed=1
    fi
  done
  [ "$changed" -eq 0 ] && say "  이미 https (변경 없음)"
  SUDO apt-get update || warn "apt update 일부 실패 — 필터 때문일 수 있으니 계속 진행"
}

# --- 2. CUDA PATH -------------------------------------------------------------
# JetPack이 CUDA 12.6 / cuDNN 9.3 / TensorRT 10.3을 이미 깔아두지만 PATH가 안 잡혀 있다.
stage_cuda_path() {
  say "CUDA PATH를 ~/.bashrc에 등록"
  [ -d "$CUDA_DIR" ] || warn "$CUDA_DIR 가 없다 — JetPack 버전이 다를 수 있음"
  if grep -q "$CUDA_DIR/bin" "$HOME/.bashrc" 2>/dev/null; then
    say "  이미 등록됨"
  else
    {
      echo ""
      echo "# CUDA (JetPack 기본 설치본) — bridge_drone_ws 셋업이 추가"
      echo "export PATH=$CUDA_DIR/bin:\$PATH"
      echo "export LD_LIBRARY_PATH=$CUDA_DIR/lib64:\${LD_LIBRARY_PATH:-}"
    } >> "$HOME/.bashrc"
    say "  등록 완료"
  fi
}

# --- 3. ROS 2 Humble ----------------------------------------------------------
stage_ros() {
  say "ROS 2 Humble 설치"
  if [ -f /opt/ros/humble/setup.bash ]; then
    say "  이미 설치됨"
  else
    apt_retry software-properties-common curl gnupg lsb-release || die "기본 도구 설치 실패"
    SUDO add-apt-repository -y universe
    SUDO curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      -o /usr/share/keyrings/ros-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
      | SUDO tee /etc/apt/sources.list.d/ros2.list > /dev/null
    apt_update_retry ros-humble-ros-base \
      || die "ROS 저장소 목록을 못 받았다 — 캠퍼스망 필터가 지속적으로 가로채는 중. 잠시 후 재실행할 것"
    apt_retry ros-humble-ros-base ros-dev-tools python3-colcon-common-extensions \
      || die "ROS 2 설치 실패"
  fi

  # 프로젝트가 쓰는 ROS 패키지들
  apt_retry ros-humble-rtabmap-ros ros-humble-realsense2-camera \
            ros-humble-cv-bridge ros-humble-message-filters \
            ros-humble-rosbag2-storage-default-plugins \
    || warn "일부 ROS 패키지 설치 실패 — 개별로 재시도할 것"

  if ! grep -q '/opt/ros/humble/setup.bash' "$HOME/.bashrc" 2>/dev/null; then
    echo "source /opt/ros/humble/setup.bash" >> "$HOME/.bashrc"
    say "  ~/.bashrc에 자동 소싱 추가"
  fi
}

# --- 4. librealsense (소스 빌드) ----------------------------------------------
# Jetson/ARM용 apt 패키지가 없어서 소스 빌드가 필요하다. 2026-07-09에 두 번
# 실패했던 지점을 미리 반영해뒀다(아래 cmake 옵션 주석 참고).
stage_librealsense() {
  say "librealsense 소스 빌드 (10~15분)"
  if python3 -c 'import pyrealsense2' 2>/dev/null; then
    say "  pyrealsense2 이미 사용 가능 — 건너뜀"
    return 0
  fi

  apt_retry git cmake build-essential libssl-dev libusb-1.0-0-dev pkg-config \
            libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev v4l-utils \
    || die "빌드 의존성 설치 실패"
  # libglu1-mesa-dev: 없으면 GL/glu.h 헤더 없음으로 빌드가 깨진다(2026-07-09 실패 ①)
  # v4l-utils: setup_udev_rules.sh가 내부에서 v4l2-ctl을 호출하는데, 없으면
  #   "v4l2-ctl not found"로 조용히 중단되고 규칙이 설치되지 않는다(2026-09-09).
  #   RSUSB 백엔드로 빌드하므로 이 규칙이 없으면 비root로 카메라를 못 연다.

  local src="$HOME/librealsense"
  [ -d "$src" ] || git clone --depth 1 https://github.com/IntelRealSense/librealsense.git "$src"

  # udev 규칙: 카메라가 이미 꽂혀 있으면 스크립트 내부에서 read -p로 멈춘다.
  # 비대화형(SSH)에서는 stdin에 개행을 하나 더 흘려줘야 안 걸린다(2026-07-09).
  if ! ( cd "$src" && printf '\n\n' | SUDO ./scripts/setup_udev_rules.sh ); then
    # 공식 스크립트는 대화형 프롬프트와 v4l2-ctl 의존성 때문에 자동 실행에서 잘 깨진다.
    # 실제로 하는 일은 규칙 파일 복사 + udev 재적용뿐이라 직접 해준다.
    warn "공식 udev 스크립트 실패 — 규칙 파일을 직접 설치"
    SUDO cp "$src"/config/*.rules /etc/udev/rules.d/ \
      && SUDO udevadm control --reload-rules \
      && SUDO udevadm trigger \
      && say "  udev 규칙 직접 설치 완료" \
      || warn "udev 규칙 설치 실패 — 비root로 카메라를 못 열 수 있음"
  fi

  mkdir -p "$src/build"
  ( cd "$src/build" && cmake .. \
      -DFORCE_RSUSB_BACKEND=true \
      -DBUILD_PYTHON_BINDINGS=true \
      -DPYTHON_EXECUTABLE="$(command -v python3)" \
      -DBUILD_EXAMPLES=false \
      -DBUILD_GRAPHICAL_EXAMPLES=false \
      -DCMAKE_BUILD_TYPE=Release \
    && make -j"$(nproc)" && SUDO make install && SUDO ldconfig ) \
    || die "librealsense 빌드 실패"
  # FORCE_RSUSB_BACKEND: 커널 패치 없이 USB 백엔드를 쓴다
  # BUILD_*EXAMPLES=false: GUI 예제에서 gluPerspective 링크 에러가 계속 나는데
  #   우리한텐 3D 뷰어가 필요 없다(2026-07-09 실패 ②) — 통째로 끈다

  # 소스 빌드(2.58.4)를 apt의 ros-humble-librealsense2(2.58.3)보다 우선 로드시킨다.
  # ROS를 소싱하면 LD_LIBRARY_PATH에 /opt/ros/humble/lib이 앞서서 구버전이 먼저 잡히고,
  # 그러면 pyrealsense2가 `undefined symbol: rs2_get_frame_gpu_data_or_upload`로
  # import에 실패한다(2026-09-09에 실제로 발생). ROS 환경 밖에서는 멀쩡히 되기 때문에
  # **ROS를 소싱한 상태로 확인해야만 드러나는** 종류의 문제다.
  # soname이 같은 2.58이라 새 쪽으로 통일해도 ROS 카메라 노드는 정상 동작한다
  # (28.2Hz 프레임 발행까지 실측 확인).
  if ! grep -q 'usr/local/lib.*LD_LIBRARY_PATH' "$HOME/.bashrc" 2>/dev/null; then
    {
      echo ""
      echo "# librealsense 소스 빌드를 apt의 ROS 버전보다 우선 로드 (버전 충돌 회피)"
      echo 'export LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH:-}'
    } >> "$HOME/.bashrc"
    say "  LD_LIBRARY_PATH 우선순위를 ~/.bashrc에 등록"
  fi

  say "  검증: rs-enumerate-devices --short"
  rs-enumerate-devices --short 2>/dev/null || warn "카메라가 안 보임 — 연결 확인"
}

# --- 5. PyTorch + YOLO --------------------------------------------------------
# 일반 PyPI에는 Jetson용 aarch64+CUDA 휠이 없다. NVIDIA 공식 휠(torch 2.5.0)은
# 짝 맞는 torchvision이 없어서 결국 못 쓴다 — 처음부터 Jetson AI Lab 인덱스에서
# torch/torchvision을 **짝으로** 받는 게 정답이다.
stage_torch() {
  say "PyTorch + torchvision + ultralytics 설치"
  apt_retry python3-pip || die "pip 설치 실패"

  if python3 -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null; then
    say "  torch(CUDA) 이미 사용 가능 — 건너뜀"
  else
    # 도메인은 .io가 맞다. .dev는 DNS도 안 뜬다(여기서 시간 많이 버렸음).
    python3 -m pip install --user \
      torch==2.8.0 torchvision==0.23.0 \
      --index-url https://pypi.jetson-ai-lab.io/jp6/cu126 \
      || die "torch 설치 실패 — 인덱스 URL(.io)과 JetPack 버전(jp6/cu126) 확인"
  fi

  # ultralytics를 그냥 설치하면 CPU용 generic torch를 끌어와 위 설치를 깨뜨린다.
  python3 -c 'import ultralytics' 2>/dev/null \
    || python3 -m pip install --user --no-deps ultralytics \
    || warn "ultralytics 설치 실패"

  # ultralytics가 --no-deps라 빠지는 런타임 의존성들을 따로 채운다.
  #
  # **numpy와 opencv 버전을 반드시 고정할 것(2026-09-09에 실제로 깨졌음)**:
  # Jetson AI Lab의 torch 2.8.0은 NumPy 1.x로 컴파일돼 있어서, 버전을 안 박고
  # 설치하면 pip가 numpy 2.x를 끌어와 GPU 텐서를 numpy로 바꾸는 순간
  # `RuntimeError: Numpy is not available`로 죽는다. vision_ai_node가 YOLO 결과를
  # 매 프레임 numpy로 변환하므로 이건 바로 치명적이다.
  # opencv-python도 4.11 이상은 numpy>=2를 요구해서 numpy를 다시 2.x로 끌어올린다 —
  # numpy 1.x와 같이 쓸 수 있는 4.10.x로 고정해야 조합이 유지된다.
  python3 -m pip install --user \
    'numpy==1.26.4' 'opencv-python==4.10.0.84' \
    pillow pyyaml requests scipy tqdm matplotlib pandas psutil py-cpuinfo \
    cloudpickle nvidia-ml-py polars ultralytics-thop \
    || warn "ultralytics 보조 의존성 일부 실패"

  python3 -m pip install --user pyserial || warn "pyserial 설치 실패(msp_probe.py에 필요)"

  say "  검증:"
  python3 - <<'PY' || warn "torch 검증 실패"
import torch
print('    torch', torch.__version__, '| CUDA 사용 가능:', torch.cuda.is_available(),
      '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')
PY
}

# --- 6. 워크스페이스 -----------------------------------------------------------
stage_workspace() {
  say "워크스페이스 준비: $WS"
  if [ ! -d "$WS" ]; then
    warn "$WS 가 없다. Mac에서 저장소를 복사해 올 것:"
    warn "  rsync -a --exclude build --exclude install --exclude log \\"
    warn "    '<Mac의 bridge_drone_ws>/' homin@<젯슨IP>:~/bridge_drone_ws/"
    warn "  (젯슨에는 GitHub 인증을 두지 않는 게 이 프로젝트 방침이라 clone 대신 rsync)"
    return 1
  fi
  # ROS의 setup.bash는 초기화되지 않은 변수(AMENT_TRACE_SETUP_FILES 등)를 참조해서
  # 이 스크립트의 `set -u` 아래에서는 "unbound variable"로 죽는다. 소싱하는 동안만 끈다.
  set +u
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash
  set -u
  ( cd "$WS" && colcon build --symlink-install ) || die "colcon build 실패"
  if ! grep -q "$WS/install/setup.bash" "$HOME/.bashrc" 2>/dev/null; then
    echo "source $WS/install/setup.bash" >> "$HOME/.bashrc"
  fi
  say "  빌드 완료"
}

# --- 7. 마무리 점검 -----------------------------------------------------------
stage_verify() {
  say "설치 점검"
  set +u   # 위와 같은 이유 (ROS setup.bash + set -u)
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash 2>/dev/null
  set -u
  printf '  %-24s' 'ros2';            command -v ros2 >/dev/null && echo OK || echo 없음
  printf '  %-24s' 'colcon';          command -v colcon >/dev/null && echo OK || echo 없음
  printf '  %-24s' 'rtabmap-export';  command -v rtabmap-export >/dev/null && echo OK || echo 없음
  # pyrealsense2는 **ROS를 소싱한 상태**로 확인해야 한다 — librealsense 버전 충돌은
  # ROS 환경 밖에서는 드러나지 않는다(위 stage_librealsense 주석 참고).
  export LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH:-}
  printf '  %-24s' 'pyrealsense2';    python3 -c 'import pyrealsense2' 2>/dev/null && echo OK || echo 없음
  printf '  %-24s' 'torch(CUDA)';     python3 -c 'import torch; exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null && echo OK || echo 없음
  printf '  %-24s' 'ultralytics';     python3 -c 'import ultralytics' 2>/dev/null && echo OK || echo 없음
  # 여기도 위와 같은 이유로 파이프 + grep -q 를 피한다
  local rs_out; rs_out="$(rs-enumerate-devices --short 2>/dev/null || true)"
  printf '  %-24s' 'D455F'
  case "$rs_out" in *[Dd]455*) echo OK ;; *) echo '안 보임' ;; esac
  echo ""
  say "남은 수동 작업:"
  say "  1) tailscale 재인증 — SUDO tailscale up  (브라우저 인증 필요, 원격 접속의 전제)"
  say "  2) swap 여유 확인 — free -h (학습 전에는 watchdog.sh를 반드시 함께 띄울 것)"
  say "  3) 모델 가중치는 저장소 LFS에 있다 — 워크스페이스 복사 시 함께 넘어왔는지 확인"
}

STAGES=(apt_sources cuda_path ros librealsense torch workspace verify)

if [ "${1:-}" = "--list" ]; then
  printf '%s\n' "${STAGES[@]}"
  exit 0
fi

TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=("${STAGES[@]}")

SUDO -v || die "SUDO 권한이 필요하다"
for s in "${TARGETS[@]}"; do
  echo ""
  echo "=============== $s ==============="
  "stage_$s" || warn "단계 '$s' 실패 — 이어서 진행"
done
echo ""
say "완료. 새 셸을 열거나 'source ~/.bashrc' 후 사용할 것."
