#!/usr/bin/env bash
# 녹화한 bag 하나를 넣으면 점검 리포트까지 한 번에 만든다.
#
# 왜 필요한가: 이 파이프라인은 지금까지 네 단계를 사람이 따로 실행해야 했다
# (추출 → SfM → 융합 → 리포트). 단계마다 인자가 다르고 앞 단계가 출력한 스케일을
# 손으로 옮겨 적어야 해서, 시연 중에 하기엔 위험하고 재현하기도 번거로웠다.
#
# 어디서 돌리나: **Mac(또는 데스크톱)에서 돌리는 게 맞다.** 젯슨은 녹화만 하고,
# 무거운 처리는 지상에서 한다 — 2026-10-26 실측으로 같은 탐지가 젯슨보다 Mac에서
# 훨씬 빨랐고(16초), COLMAP도 Mac에 설치돼 있다.
#
# 사용법:
#   ./process_scan.sh ~/frames/scan1                 # 이미 추출된 프레임으로
#   ./process_scan.sh ~/frames/scan1 --viewer         # 3D 뷰어도 함께 생성
#
# 프레임 추출은 ROS가 필요해 젯슨에서 따로 해야 한다(scripts/extract_frames.py).
# 추출된 디렉토리를 Mac으로 가져온 뒤 이 스크립트를 돌린다.

set -uo pipefail

FRAMES="${1:?사용법: process_scan.sh <frames 디렉토리> [--viewer]}"
shift || true
MAKE_VIEWER=0
for a in "$@"; do [ "$a" = "--viewer" ] && MAKE_VIEWER=1; done

WS="$(cd "$(dirname "$0")/.." && pwd)"
SCAN="$(basename "${FRAMES%/}")"
MODEL="${MODEL:-$WS/models/crack_seg_v3_combined_finetune.pt}"
CONF="${CONF:-0.25}"

[ -d "$FRAMES/images" ] || { echo "에러: $FRAMES/images 가 없다 — extract_frames.py 출력 디렉토리를 지정할 것" >&2; exit 1; }
[ -f "$MODEL" ] || { echo "에러: 모델을 찾을 수 없다 — $MODEL" >&2; exit 1; }

echo "=============================================="
echo " 스캔 처리: $SCAN"
echo " 프레임 $(find "$FRAMES/images" -name '*.jpg' | wc -l | tr -d ' ')장"
echo "=============================================="

# --- 1. 카메라 포즈 (COLMAP SfM) -------------------------------------------
POSES="$FRAMES/colmap/sparse/0/images.txt"
if [ -f "$POSES" ]; then
  echo "[1/4] SfM — 이미 계산돼 있어 건너뜀 (다시 하려면 $FRAMES/colmap 삭제)"
else
  echo "[1/4] SfM — 카메라 포즈 계산 (가장 오래 걸림)"
  "$WS/scripts/sfm_poses.sh" "$FRAMES" || { echo "SfM 실패" >&2; exit 1; }
fi
[ -f "$POSES" ] || { echo "에러: 포즈가 생성되지 않았다" >&2; exit 1; }

# --- 2. depth 융합 + 스케일 복원 --------------------------------------------
# 스케일은 이 단계가 계산해서 출력한다. 예전엔 그 값을 사람이 받아적어 다음
# 단계에 넘겼는데, 옮겨 적다 틀리면 모든 치수가 통째로 어긋나므로 자동으로 받는다.
echo "[2/4] depth 융합 — 실제 크기(스케일) 복원"
FUSE_LOG="$FRAMES/fuse.log"
"$WS/scripts/fuse_depth.py" \
  --poses "$POSES" --pose-format colmap \
  --depth-dir "$FRAMES/depth" --color-dir "$FRAMES/images" \
  --intrinsics "$FRAMES/intrinsics.json" \
  --scale-from-sparse "$FRAMES/colmap/sparse/0/points3D.txt" \
  --out "$FRAMES/cloud.ply" --stride 2 2>&1 | tee "$FUSE_LOG"
SCALE="$(grep -oE '스케일 [0-9.]+' "$FUSE_LOG" | head -1 | awk '{print $2}')"
[ -n "$SCALE" ] || { echo "에러: 스케일을 읽지 못했다 — $FUSE_LOG 확인" >&2; exit 1; }
echo "      복원된 스케일: $SCALE"

# --- 3. 균열 탐지 + 3D 좌표 --------------------------------------------------
echo "[3/4] 균열 탐지 및 3D 좌표 변환"
"$WS/scripts/detect_cracks_offline.py" \
  --frames "$FRAMES" --poses "$POSES" --scale "$SCALE" \
  --model "$MODEL" --conf "$CONF" --scan-name "$SCAN" \
  --out "$FRAMES/cracks.json" || { echo "탐지 실패" >&2; exit 1; }

# --- 4. 리포트 ---------------------------------------------------------------
echo "[4/4] 점검 리포트 생성"
# macOS 기본 bash(3.2)에서는 `set -u` + 빈 배열 전개가 unbound variable로 죽는다.
# 인자를 문자열로 모아 쓰면 그 함정을 피할 수 있다.
VIEWER_URL=""
if [ "$MAKE_VIEWER" = "1" ]; then
  echo "      3D 뷰어도 생성 중..."
  "$WS/scripts/make_viewer.py" --cloud "$FRAMES/cloud.ply" \
    --poses "$POSES" --scale "$SCALE" --title "$SCAN" \
    --out "$FRAMES/viewer.html" && VIEWER_URL="viewer.html"
fi
if [ -n "$VIEWER_URL" ]; then
  "$WS/scripts/make_report.py" --cracks "$FRAMES/cracks.json" \
    --out "$FRAMES/report.html" --viewer-url "$VIEWER_URL" || { echo "리포트 실패" >&2; exit 1; }
else
  "$WS/scripts/make_report.py" --cracks "$FRAMES/cracks.json" \
    --out "$FRAMES/report.html" || { echo "리포트 실패" >&2; exit 1; }
fi

echo
echo "=============================================="
echo " 완료"
echo "   리포트 : $FRAMES/report.html"
[ "$MAKE_VIEWER" = "1" ] && echo "   3D 뷰어: $FRAMES/viewer.html"
echo "   점구름 : $FRAMES/cloud.ply"
echo "=============================================="
