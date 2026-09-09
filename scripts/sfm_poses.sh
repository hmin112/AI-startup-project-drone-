#!/usr/bin/env bash
# 추출한 컬러 이미지로 COLMAP SfM을 돌려 카메라 포즈를 구한다 (A안 2단계).
#
# A안은 사진에서 **형상까지** 뽑지 않는다 — 포즈만 필요하다. 그래서 CUDA가
# 필요한 dense 단계(patch-match stereo)는 아예 돌리지 않고 sparse까지만 한다.
# 덕분에 Mac(M1 Pro)에서 CPU만으로 돌아간다.
#
# 왜 sequential_matcher인가: 입력이 연속 촬영한 프레임이라 시간순으로 이웃한
# 이미지끼리 겹친다. exhaustive_matcher는 모든 쌍을 비교해 N²로 폭발하지만
# sequential은 이웃 위주로만 비교해 훨씬 빠르고, 루프를 닫기 위한 vocab tree
# 재검출은 --SequentialMatching.loop_detection으로 따로 켠다.
#
# 사용법: ./sfm_poses.sh <frames 디렉토리> [작업 디렉토리]
#   frames 디렉토리는 extract_frames.py의 출력(images/ 하위에 jpg)

set -euo pipefail

FRAMES="${1:?사용법: sfm_poses.sh <frames 디렉토리> [작업 디렉토리]}"
WORK="${2:-$FRAMES/colmap}"
IMAGES="$FRAMES/images"

if [ ! -d "$IMAGES" ]; then
  echo "에러: $IMAGES 가 없다 — extract_frames.py 출력 디렉토리를 지정할 것" >&2
  exit 1
fi

command -v colmap >/dev/null || { echo "에러: colmap이 없다 (brew install colmap)" >&2; exit 1; }

mkdir -p "$WORK/sparse"
DB="$WORK/database.db"
N_IMG=$(find "$IMAGES" -name '*.jpg' | wc -l | tr -d ' ')
echo "=== COLMAP SfM 시작 — 이미지 ${N_IMG}장 ==="

# 카메라 모델을 PINHOLE로 고정하고 내부파라미터를 공유시킨다.
# aligned_depth_to_color 스트림은 이미 왜곡보정된 컬러 기준이라 왜곡계수가 0이고,
# 모든 프레임이 같은 카메라이므로 공유하는 게 정확도·속도 양쪽에 유리하다.
# GPU 옵션 이름이 COLMAP 버전마다 다르다: 3.x는 SiftExtraction/SiftMatching,
# 4.x는 FeatureExtraction/FeatureMatching. 설치된 버전에 맞춰 고른다.
if colmap feature_extractor --help 2>&1 | grep -q 'FeatureExtraction.use_gpu'; then
  EXTRACT_GPU_OPT='--FeatureExtraction.use_gpu'
  MATCH_GPU_OPT='--FeatureMatching.use_gpu'
else
  EXTRACT_GPU_OPT='--SiftExtraction.use_gpu'
  MATCH_GPU_OPT='--SiftMatching.use_gpu'
fi
# GPU 가속을 먼저 시도하고, 안 되면 CPU로 떨어진다(맥엔 CUDA가 없어서 실패할 수 있음).
USE_GPU="${USE_GPU:-1}"

echo "[1/4] 특징점 추출 (GPU=$USE_GPU)"
if ! colmap feature_extractor \
  --database_path "$DB" \
  --image_path "$IMAGES" \
  --ImageReader.camera_model PINHOLE \
  --ImageReader.single_camera 1 \
  "$EXTRACT_GPU_OPT" "$USE_GPU"; then
  echo "  GPU 추출 실패 — CPU로 재시도"
  USE_GPU=0
  colmap feature_extractor \
    --database_path "$DB" \
    --image_path "$IMAGES" \
    --ImageReader.camera_model PINHOLE \
    --ImageReader.single_camera 1 \
    "$EXTRACT_GPU_OPT" 0
fi

echo "[2/4] 순차 매칭 (+루프 검출)"
colmap sequential_matcher \
  --database_path "$DB" \
  "$MATCH_GPU_OPT" "$USE_GPU" \
  --SequentialMatching.overlap 10

echo "[3/4] 재구성(mapper) — 가장 오래 걸리는 단계"
colmap mapper \
  --database_path "$DB" \
  --image_path "$IMAGES" \
  --output_path "$WORK/sparse"

echo "[4/4] 텍스트로 변환"
if [ ! -d "$WORK/sparse/0" ]; then
  echo "에러: 재구성 결과가 없다 — 텍스처 부족으로 매칭이 실패했을 수 있다" >&2
  echo "      $DB 의 매칭 수를 확인하거나 --every-n을 낮춰 더 촘촘한 프레임으로 재시도" >&2
  exit 1
fi
colmap model_converter \
  --input_path "$WORK/sparse/0" \
  --output_path "$WORK/sparse/0" \
  --output_type TXT

REGISTERED=$(grep -c '^[0-9]' "$WORK/sparse/0/images.txt" 2>/dev/null | head -1 || echo 0)
echo "=== 완료 ==="
echo "  포즈: $WORK/sparse/0/images.txt"
echo "  희소점: $WORK/sparse/0/points3D.txt"
echo "  등록된 이미지: 약 $((REGISTERED / 2)) / ${N_IMG}장"
echo ""
echo "다음: ./fuse_depth.py --poses $WORK/sparse/0/images.txt --pose-format colmap \\"
echo "        --depth-dir $FRAMES/depth --intrinsics $FRAMES/intrinsics.json \\"
echo "        --scale-from-sparse $WORK/sparse/0/points3D.txt --out $WORK/colmap_cloud.ply"
