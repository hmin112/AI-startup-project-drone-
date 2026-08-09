#!/usr/bin/env bash
# 착륙 후 RTAB-Map DB로부터 정밀 3D 재구성 산출물을 생성한다.
#
# docs/bridge_drone_project_summary.md 5번 항목("착륙 후엔 저장해둔
# 원본 데이터를 옮겨서 정밀 3D 맵 재구성")의 설계를 실제로 구현한 것 —
# 그전까지는 recorder_node가 원본 영상을, rtabmap이 -d 옵션으로 키프레임
# 기반 맵 DB를 저장만 했을 뿐 "착륙 후 처리" 단계 자체가 없었다.
#
# rtabmap-export(ros-humble-rtabmap-ros 설치 시 함께 들어오는 CLI,
# /opt/ros/humble/bin/rtabmap-export)를 감싸서 이 프로젝트에 필요한
# 세 가지 산출물(포인트클라우드, 텍스처 메쉬, 비행 경로)을 한 번에 뽑는다.
#
# 사용법: ./reconstruct_from_flight.sh <rtabmap.db 경로> [출력 디렉토리]
# 기본 DB 위치는 rtabmap_odom/rtabmap 노드 기본값인 ~/.ros/rtabmap.db.

set -euo pipefail

DB_PATH="${1:?사용법: reconstruct_from_flight.sh <rtabmap.db 경로> [출력 디렉토리]}"
OUT_DIR="${2:-$(dirname "$DB_PATH")/reconstruction_$(date +%Y%m%d_%H%M%S)}"

if [ ! -f "$DB_PATH" ]; then
  echo "에러: DB 파일을 찾을 수 없음: $DB_PATH" >&2
  exit 1
fi

if ! command -v rtabmap-export >/dev/null 2>&1; then
  echo "에러: rtabmap-export를 찾을 수 없음 — 'source /opt/ros/humble/setup.bash'를 먼저 실행했는지 확인할 것" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

echo "[1/3] 포인트클라우드(PLY) 추출..."
rtabmap-export --cloud --output_dir "$OUT_DIR" "$DB_PATH"

echo "[2/3] 텍스처 메쉬(OBJ) 생성..."
rtabmap-export --mesh --texture --output_dir "$OUT_DIR" "$DB_PATH"

echo "[3/3] 비행 경로(포즈) 추출..."
rtabmap-export --poses --output_dir "$OUT_DIR" "$DB_PATH"

echo ""
echo "완료: $OUT_DIR"
ls -la "$OUT_DIR"
