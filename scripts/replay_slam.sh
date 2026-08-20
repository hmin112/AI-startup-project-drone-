#!/usr/bin/env bash
# capture_bag.sh로 녹화해둔 rosbag을 느린 속도로 재생하면서 SLAM을 돌려
# 지도 DB(~/.ros/rtabmap.db)를 만든다. 배경과 설계 의도는 capture_bag.sh 주석 참고.
#
# 재생 속도(--rate)를 왜 1보다 낮추나:
#   젯슨에서 rgbd_odometry의 프레임당 처리 시간이 0.14~0.22s인데 bag은
#   15fps(0.067s 간격)로 재생된다. 등속(1.0)으로 재생하면 처리가 못 따라가
#   실시간 때와 똑같이 프레임이 밀린다. 0.3이면 프레임 간격이 0.22s가 되어
#   처리 시간과 얼추 맞음 — 여유를 두려면 더 낮출 것.
#   (launch 쪽에서 always_process_most_recent_frame=false로 버리지 않고
#    큐잉하게 해뒀지만, 큐도 유한하므로 속도 자체를 낮추는 게 근본적이다.)
#
# 사용법: ./replay_slam.sh <bag 경로> [재생속도]
#   예) ./replay_slam.sh ~/bags/wall_20260820_120000 0.3

set -euo pipefail

BAG="${1:?사용법: replay_slam.sh <bag 경로> [재생속도]}"
RATE="${2:-0.3}"
WS_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$BAG" ]; then
  echo "에러: bag 디렉토리를 찾을 수 없음 — $BAG" >&2
  exit 1
fi

echo "=== 재생 SLAM 시작 ==="
echo "  bag:  $BAG"
echo "  rate: $RATE"

setsid nohup ros2 launch "$WS_DIR/launch/replay_slam.launch.py" \
  > /tmp/replay_slam.log 2>&1 < /dev/null &

# 노드가 토픽 구독을 마치기 전에 재생을 시작하면 앞부분 프레임을 통째로
# 놓친다 — SLAM은 시작 구간이 특히 중요하므로 충분히 기다린다.
sleep 12

echo "=== bag 재생 ==="
# --clock: /clock 발행(위 launch의 use_sim_time과 짝)
ros2 bag play "$BAG" --clock --rate "$RATE"

# 재생이 끝나도 rtabmap이 마지막 프레임들을 처리 중일 수 있어 여유를 준다
echo "=== 마무리 대기 ==="
sleep 15

# SIGINT로 정상 종료해야 rtabmap이 DB를 제대로 닫는다
pkill -INT -f 'ros2 launch.*replay_slam' || true
pkill -INT -f 'rtabmap' || true
pkill -INT -f 'rgbd_odometry' || true
sleep 8
pkill -f 'replay_slam|rtabmap|rgbd_odometry|static_transform_publisher' || true

echo "=== 완료 ==="
ls -la "$HOME/.ros/rtabmap.db" 2>/dev/null || echo "경고: rtabmap.db가 생성되지 않음"
