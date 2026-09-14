#!/usr/bin/env python3
"""추출해둔 프레임에 균열 탐지를 돌려 3D 위치까지 뽑는다 (오프라인 경로).

왜 별도로 만드나: 기존 균열 경로(`vision_ai` → `crack_fusion` → `crack_collector`)는
RTAB-Map 재생 위에서 돌도록 배선돼 있는데, 2026-09-09에 만든 재구성 경로는
COLMAP(SfM) 포즈를 쓴다. 포즈 품질은 COLMAP 쪽이 낫고(재투영 오차 1.00px) 같은
프레임을 이미 추출해뒀으므로, 그 포즈로 탐지를 3D에 얹는 경로를 따로 둔다.

계산은 기존과 동일한 방식을 재사용한다 — 마스크에 `cv2.minAreaRect`를 씌워
회전 사각형의 긴 변/짧은 변을 길이/폭으로 삼고(2026-07-12 결정), 픽셀을 depth로
역투영해 mm를 구하고, 반복 관측을 map 좌표 반경으로 병합하며 크기는 **중앙값**을
쓴다(튀는 값 때문에 평균을 쓰지 않는 이유는 crack_collector_node 주석 참고).

**헛탐지 문제**: 2026-09-14에 균열이 없는 책상 스캔으로 재본 결과, 기본 임계값
0.25에서도 388장 중 18장에서 19건이 탐지됐고 최고 confidence가 0.557이었다.
실제 균열 탐지가 0.29~0.36(2026-08-13 실측)이었으므로 **confidence만으로는 진짜와
구분할 수 없다.** 그래서 이 스크립트는 병합된 각 후보의 `observations`(몇 프레임에서
보였는지)를 반드시 함께 내놓는다 — 진짜 균열은 여러 프레임에 걸쳐 같은 자리에서
보이고 헛탐지는 한두 번 튀고 마는 차이를 거르라는 뜻이다.

사용법:
    ./detect_cracks_offline.py --frames ~/frames/scan1 \\
        --poses ~/frames/scan1/colmap/sparse/0/images.txt --scale 0.158481 \\
        --model models/crack_seg_v3_combined_finetune.pt --out cracks.json
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fuse_depth import read_colmap_images  # noqa: E402


def nearest_valid_depth(depth_img, u, v, max_radius=5):
    """무효(0) 픽셀이면 주변에서 가장 가까운 유효 depth를 찾는다.

    2026-08-13에 실제 벽 틈을 재려다 bbox 모서리 4개 중 3개가 depth=0에 걸려
    측정이 통째로 실패한 뒤 `measurement.py`에 넣은 폴백과 같은 규칙이다.
    반경을 더 넓히면 결함과 무관한 배경 depth를 끌어와 오히려 부정확해진다.
    """
    h, w = depth_img.shape
    u, v = int(round(u)), int(round(v))
    if not (0 <= v < h and 0 <= u < w):
        return 0
    if depth_img[v, u] > 0:
        return depth_img[v, u]
    for r in range(1, max_radius + 1):
        y0, y1 = max(0, v - r), min(h, v + r + 1)
        x0, x1 = max(0, u - r), min(w, u + r + 1)
        patch = depth_img[y0:y1, x0:x1]
        valid = patch[patch > 0]
        if valid.size:
            return int(np.median(valid))
    return 0


def deproject(u, v, z_m, fx, fy, cx, cy):
    """픽셀 + 깊이 -> 카메라 광학 프레임 3D(미터).

    aligned_depth_to_color 스트림은 이미 왜곡보정된 컬러 기준이라 왜곡계수가 0이고,
    따라서 단순 핀홀 역투영이 SDK의 rs2_deproject_pixel_to_point와 같은 결과를 준다
    (pyrealsense2가 없는 Mac에서도 돌게 하려고 직접 계산한다).
    """
    return np.array([(u - cx) * z_m / fx, (v - cy) * z_m / fy, z_m], dtype=np.float64)


def measure_mask(mask, depth_img, depth_scale, intr):
    """마스크 하나에서 길이/폭(mm)과 중심 3D 좌표를 낸다."""
    fx, fy, cx, cy = intr['fx'], intr['fy'], intr['cx'], intr['cy']
    ys, xs = np.nonzero(mask)
    if xs.size < 8:
        return None
    pts = np.stack([xs, ys], 1).astype(np.float32)
    (ccx, ccy), (w_px, h_px), _ = cv2.minAreaRect(pts)

    cz = nearest_valid_depth(depth_img, ccx, ccy) * depth_scale
    if cz <= 0:
        return None
    center3d = deproject(ccx, ccy, cz, fx, fy, cx, cy)

    # 픽셀 길이를 그 거리에서의 실제 크기로 환산. 회전 사각형의 긴 변이 길이,
    # 짧은 변이 폭 — 균열은 길고 가늘며 대각선인 경우가 많아 축정렬 bbox는 부적합.
    long_px, short_px = max(w_px, h_px), min(w_px, h_px)
    return {
        'length_mm': float(long_px / fx * cz * 1000.0),
        'width_mm': float(short_px / fx * cz * 1000.0),
        'center_camera_m': [float(v) for v in center3d],
        'pixels': int(xs.size),
    }


def merge(observations, radius_m):
    """map 좌표가 가까운 관측들을 하나의 균열 후보로 병합한다."""
    clusters = []
    for obs in observations:
        p = np.array(obs['map_position_m'])
        for c in clusters:
            if np.linalg.norm(p - c['sum'] / c['n']) < radius_m:
                c['sum'] += p
                c['n'] += 1
                c['obs'].append(obs)
                break
        else:
            clusters.append({'sum': p.copy(), 'n': 1, 'obs': [obs]})

    out = []
    for c in clusters:
        lens = [o['length_mm'] for o in c['obs']]
        wids = [o['width_mm'] for o in c['obs']]
        confs = [o['confidence'] for o in c['obs']]
        out.append({
            'map_position_m': (c['sum'] / c['n']).tolist(),
            'observations': c['n'],
            'length_mm_median': float(np.median(lens)),
            'width_mm_median': float(np.median(wids)),
            'confidence_max': float(max(confs)),
            'confidence_median': float(np.median(confs)),
            'frames': sorted({o['frame'] for o in c['obs']}),
        })
    out.sort(key=lambda d: -d['observations'])
    return out


def main():
    ap = argparse.ArgumentParser(description='프레임에 균열 탐지를 돌려 3D 위치까지')
    ap.add_argument('--frames', required=True, help='extract_frames.py 출력 디렉토리')
    ap.add_argument('--poses', required=True, help='COLMAP images.txt')
    ap.add_argument('--scale', type=float, required=True, help='fuse_depth.py가 낸 스케일')
    ap.add_argument('--model', required=True, help='YOLO seg 가중치(.pt)')
    ap.add_argument('--out', required=True, help='출력 JSON')
    ap.add_argument('--conf', type=float, default=0.25, help='탐지 임계값(기본 0.25)')
    ap.add_argument('--merge-radius-mm', type=float, default=150.0,
                    help='같은 균열로 묶을 map 좌표 반경(기본 150mm)')
    ap.add_argument('--min-observations', type=int, default=1,
                    help='이보다 적게 관측된 후보는 버린다 — 헛탐지를 거르는 주된 수단')
    args = ap.parse_args()

    from ultralytics import YOLO

    with open(os.path.join(args.frames, 'intrinsics.json'), encoding='utf-8') as f:
        intr = json.load(f)
    depth_scale = intr.get('depth_scale_m', 0.001)
    poses = read_colmap_images(args.poses)
    model = YOLO(args.model)
    print('포즈 %d개, 탐지 임계값 %.2f' % (len(poses), args.conf))

    observations = []
    for i, name in enumerate(sorted(poses)):
        img_path = os.path.join(args.frames, 'images', name)
        depth_path = os.path.join(args.frames, 'depth', os.path.splitext(name)[0] + '.png')
        if not (os.path.exists(img_path) and os.path.exists(depth_path)):
            continue
        depth_img = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
        res = model.predict(img_path, conf=args.conf, verbose=False)[0]
        if res.masks is None or res.boxes is None or len(res.boxes) == 0:
            continue

        cam_to_world = poses[name].copy()
        cam_to_world[:3, 3] *= args.scale
        for mask_xy, conf in zip(res.masks.data.cpu().numpy(),
                                 res.boxes.conf.cpu().numpy()):
            m = cv2.resize(mask_xy, (depth_img.shape[1], depth_img.shape[0]),
                           interpolation=cv2.INTER_NEAREST) > 0.5
            meas = measure_mask(m, depth_img, depth_scale, intr)
            if meas is None:
                continue
            world = cam_to_world[:3, :3] @ np.array(meas['center_camera_m']) + cam_to_world[:3, 3]
            observations.append({**meas, 'frame': name, 'confidence': float(conf),
                                 'map_position_m': world.tolist()})
        if (i + 1) % 50 == 0:
            print('  %d/%d 프레임, 관측 %d건' % (i + 1, len(poses), len(observations)))

    cracks = merge(observations, args.merge_radius_mm / 1000.0)
    kept = [c for c in cracks if c['observations'] >= args.min_observations]

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'cracks': kept, 'total_observations': len(observations),
                   'clusters_before_filter': len(cracks),
                   'conf_threshold': args.conf,
                   'min_observations': args.min_observations}, f, indent=2)

    print('\n관측 %d건 -> 후보 %d개 (관측 %d회 이상만 남기면 %d개)'
          % (len(observations), len(cracks), args.min_observations, len(kept)))
    print('\n관측 횟수 분포 (헛탐지는 1~2회에 몰린다):')
    from collections import Counter
    for n, c in sorted(Counter(x['observations'] for x in cracks).items()):
        print('  %2d회 관측: %d개' % (n, c))
    if kept:
        print('\n상위 후보:')
        for c in kept[:8]:
            print('  관측 %2d회 | 길이 %6.1fmm 폭 %5.1fmm | conf 최대 %.2f | 위치 %s'
                  % (c['observations'], c['length_mm_median'], c['width_mm_median'],
                     c['confidence_max'],
                     np.round(c['map_position_m'], 2).tolist()))
    print('\n저장: %s' % args.out)


if __name__ == '__main__':
    main()
