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
# 해상도를 낮춘 이유 (2026-08-20 실측):
#   젯슨 microSD의 순차 쓰기 속도가 25.3MB/s(dd 실측)라, 1280x720x30 원본
#   (약 138MB/s)은 물리적으로 녹화가 불가능. 848x480x15 + rosbag2 zstd
#   메시지 압축으로 약 17MB/s가 되어 한계 안에 들어옴(20초 테스트에서
#   321MB, 프레임 드롭 없음).
#   대가: 픽셀당 실제 크기가 1m 거리에서 1.55mm/px → 2.34mm/px로 나빠져
#   측정 가능한 최소 결함 크기가 대략 3~5mm → 5~7mm가 됨. 미세 균열
#   정밀 측정이 목적이면 이 경로 대신 라이브 1280x720 경로를 쓰거나,
#   USB SSD를 달아 저장 병목 자체를 없앨 것(docs 8번 항목 8).
#
# 사용법:
#   ./capture_bag.sh start [이름]   # 카메라 기동 + 녹화 시작
#   ./capture_bag.sh stop           # 녹화/카메라 정지 + 결과 요약

set -euo pipefail

BAG_DIR="${BAG_DIR:-$HOME/bags}"
STATE_FILE="/tmp/capture_bag.state"
PROFILE="${PROFILE:-848x480x15}"

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
