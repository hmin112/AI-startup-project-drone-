#!/usr/bin/env bash
# 촬영 전용 — SLAM/YOLO를 전혀 띄우지 않고 D455F 원본 프레임만 rosbag2로 녹화.
#
# 왜 촬영과 처리를 분리하나 (2026-08-20):
#   젯슨에서 실시간으로 SLAM을 돌리면 rgbd_odometry의 프레임당 처리 시간이
#   0.14~0.22s인데 카메라는 그보다 훨씬 빠르게 프레임을 밀어넣어서, 대부분의
#   프레임이 버려진다(로그의 "Dropping image/scan data" 경고). 버려진 만큼
#   연속 프레임 사이의 움직임이 커져 정합이 실패하고, 그게 오도메트리 리셋 →
#   지도 조각화로 이어짐 (2026-08-19 연필꽂이 스캔: 9번 리셋, 노드 749개가
#   8개 map_id로 조각남).
#   촬영 때는 카메라만 돌려 CPU를 비워두고, 나중에 replay_slam.sh로 느리게
#   재생하면서 모든 프레임을 빠짐없이 처리한다. 같은 데이터로 파라미터를
#   바꿔가며 몇 번이고 재시도할 수 있다는 것도 큰 장점.
#
# 프로필 기본값이 1280x720x5인 이유 (2026-09-09 실측, 이전 848x480x15에서 변경):
#   저장 병목은 그대로다 — microSD 순차 쓰기 29.4MB/s(dd 실측). 그런데 해상도를
#   낮출 게 아니라 **프레임레이트를 낮추는 게 맞다**는 걸 알았다.
#   재구성(SfM/photogrammetry)에서 중요한 건 프레임 수가 아니라 겹침과 해상도인데,
#   천천히 움직이면 5fps로도 겹침이 넘치기 때문이다(실측: 프레임 간 평균 이동 64mm,
#   1m 거리 화각 폭이 약 1.8m라 겹침 96%).
#     848x480x15  : 약 17MB/s, 1m에서 2.34mm/px
#     1280x720x5  : 약  8MB/s, 1m에서 1.55mm/px   <- 데이터는 절반, 해상도는 복구
#   즉 USB SSD 없이도 2026-08-20에 포기했던 해상도를 되찾았다. 측정 가능한 최소
#   결함 크기도 5~7mm에서 3~5mm로 돌아온다(docs 8번 항목 8/11).
#   저장해둔 공장 캘리브레이션이 1280x720 기준이라 내부파라미터가 정확히 일치하는
#   것도 이 프로필의 이점(models/camera_calibration/d455f_intrinsics_1280x720.json).
#
#   빠르게 움직이며 찍어야 하면(실제 비행 등) PROFILE=848x480x15로 되돌릴 수 있다.
#
# 사용법:
#   ./capture_bag.sh start [이름]   # 카메라 기동 + 녹화 시작
#   ./capture_bag.sh stop           # 녹화/카메라 정지 + 결과 요약

set -euo pipefail

BAG_DIR="${BAG_DIR:-$HOME/bags}"
STATE_FILE="/tmp/capture_bag.state"
PROFILE="${PROFILE:-1280x720x5}"

TOPICS=(
  /camera/camera/color/image_raw
  /camera/camera/aligned_depth_to_color/image_raw
  /camera/camera/color/camera_info
  /camera/camera/aligned_depth_to_color/camera_info
  /tf_static
)

start() {
  local name="${1:-scan_$(date +%Y%m%d_%H%M%S)}"
  local out="$BAG_DIR/$name"

  if [ -e "$out" ]; then
    echo "에러: 이미 존재하는 경로 — $out" >&2
    exit 1
  fi
  mkdir -p "$BAG_DIR"

  echo "[1/2] 카메라 기동 ($PROFILE)..."
  setsid nohup ros2 run realsense2_camera realsense2_camera_node --ros-args \
    -r __node:=camera -r __ns:=/camera \
    -p align_depth.enable:=true \
    -p enable_color:=true -p enable_depth:=true \
    -p enable_infra1:=false -p enable_infra2:=false \
    -p pointcloud.enable:=false \
    -p "depth_module.depth_profile:=$PROFILE" \
    -p "rgb_camera.color_profile:=$PROFILE" \
    > /tmp/capture_camera.log 2>&1 < /dev/null &

  # 카메라가 실제로 프레임을 낼 때까지 대기 — 바로 녹화를 걸면 앞부분이 빈다
  local waited=0
  until ros2 topic list 2>/dev/null | grep -q '/camera/camera/color/image_raw'; do
    sleep 1
    waited=$((waited + 1))
    if [ "$waited" -gt 40 ]; then
      echo "에러: 카메라 토픽이 안 올라옴 — /tmp/capture_camera.log 확인" >&2
      exit 1
    fi
  done
  sleep 3  # 자동노출 수렴 여유

  echo "[2/2] 녹화 시작 → $out"
  setsid nohup ros2 bag record \
    --compression-mode message --compression-format zstd \
    -o "$out" "${TOPICS[@]}" \
    > /tmp/capture_bag.log 2>&1 < /dev/null &

  echo "$out" > "$STATE_FILE"
  echo "녹화 중. 끝나면 './capture_bag.sh stop'"
}

stop() {
  if [ ! -f "$STATE_FILE" ]; then
    echo "에러: 진행 중인 녹화 정보가 없음($STATE_FILE)" >&2
    exit 1
  fi
  local out
  out="$(cat "$STATE_FILE")"

  # 녹화 프로세스에 SIGINT를 보내 메타데이터가 정상적으로 닫히게 함
  # (SIGKILL로 죽이면 metadata.yaml이 안 써져서 bag이 못 읽히게 됨)
  pkill -INT -f 'ros2 bag record' || true
  sleep 3
  pkill -f 'realsense2_camera_node' || true
  rm -f "$STATE_FILE"

  echo "=== 녹화 결과 ==="
  du -sh "$out" 2>/dev/null || true
  ros2 bag info "$out" 2>&1 | grep -E 'Duration|Messages|Count' || true
}

case "${1:-}" in
  start) shift; start "$@" ;;
  stop) stop ;;
  *) echo "사용법: $0 {start [이름]|stop}" >&2; exit 1 ;;
esac
