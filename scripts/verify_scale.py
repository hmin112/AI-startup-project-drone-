#!/usr/bin/env python3
"""인쇄한 ArUco 타겟으로 "눈금"을 대조한다 — depth 정확도와 SfM 스케일을 따로.

`make_scale_target.py`로 뽑은 A4 타겟을 벽에 붙이고 평소처럼 스캔한 뒤 돌린다.
**두 가지는 서로 다른 문제이고, 여기서 따로 잰다.**

**검증 1 — depth가 거리를 맞게 재는가** (마커 실제 크기 필요)
    한 프레임 안에서 마커 중심 사이 거리를 재서 인쇄 치수와 비교한다. 한 프레임
    안의 치수는 depth와 내부파라미터만으로 정해지므로 SfM 스케일과 무관하다.

**검증 2 — SfM 스케일이 맞는가** (마커 크기 불필요)
    같은 마커를 서로 떨어진 두 지점에서 보고 각각 월드로 보냈을 때 같은 자리에
    떨어지는지 본다. 스케일이 k배 틀리면 카메라 중심이 그만큼 어긋나므로
    두 결과가 **촬영 지점 사이 거리에 비례해서** 벌어진다:
        어긋남 = (k-1)/k × 두 지점 사이 거리
    이 기울기를 회귀로 구하면 그게 곧 스케일 오차다. 부호까지 나온다 —
    어긋남을 이동 방향에 투영하면 양수는 "스케일이 크다"는 뜻이다.

**핵심: 코너 3D 위치를 depth에서 직접 읽지 않는다.** 0.65m에서 depth 노이즈는
σ≈9mm라, 코너 네 점을 그대로 쓰면 130mm 거리의 오차가 ±13mm(10%)가 되어
아무것도 검증하지 못한다. 대신 **마커 내부 픽셀 전부로 평면을 맞추고, 코너
픽셀의 시선을 그 평면과 교차**시킨다. 코너 위치는 영상에서 서브픽셀로 정확히
나오고 depth는 평면 하나로만 들어가므로, 수천 점이 평균돼 노이즈가 크게 준다.

**마커 '한 변'보다 '중심 사이 거리'를 믿을 것.** 검출기가 주는 코너는 바깥 검은
테두리의 중심선이라 실제 변보다 약 1픽셀 짧게 나온다. 0.65m에서 40mm 마커는
약 40픽셀이므로 이 편향이 2.5%나 된다. 중심은 네 코너의 평균이라 이 편향이
상쇄되고, 거리도 130~238mm로 길어 상대오차가 작다.

쓰는 법:
    python3 scripts/verify_scale.py --frames ~/frames/target1 \\
        --truth ~/scale_target.json \\
        --poses ~/frames/target1/colmap/sparse/0/images.txt --scale 0.1584
    python3 scripts/verify_scale.py --self-test    # 하드웨어 없이 수식 검증
"""

import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plane_sigma import fit_plane_ransac, refine_plane          # noqa: E402
from fuse_depth import read_colmap_images                       # noqa: E402


def detector(dict_name='DICT_5X5_50'):
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    p = cv2.aruco.DetectorParameters()
    # 코너를 서브픽셀로 다듬는다 — 이 정확도가 그대로 치수 정확도가 된다
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 5
    return cv2.aruco.ArucoDetector(d, p)


def deproject(u, v, z, K):
    """픽셀 + 거리 → 카메라 광학 좌표계 3D."""
    fx, fy, cx, cy = K
    return np.stack([(u - cx) * z / fx, (v - cy) * z / fy, z], axis=-1)


def marker_corners_3d(corners_px, depth_m, K, min_px=200):
    """마커 네 코너의 3D 위치. 내부 픽셀로 평면을 맞추고 시선을 교차시킨다.

    실패하면 None (깊이가 너무 비거나 평면이 안 나올 때).
    """
    h, w = depth_m.shape
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, np.round(corners_px).astype(np.int32), 1)
    vs, us = np.nonzero(mask & (depth_m > 0))
    if us.size < min_px:
        return None

    pts = deproject(us.astype(np.float64), vs.astype(np.float64), depth_m[vs, us], K)
    normal, d, inliers = fit_plane_ransac(pts, threshold_m=0.01)
    if inliers.sum() < min_px // 2:
        return None
    normal, d = refine_plane(pts[inliers], normal, d, band_m=0.02)

    # 코너 시선(단위벡터)과 평면의 교점. n·(t·r) + d = 0  →  t = -d / (n·r)
    fx, fy, cx, cy = K
    rays = np.stack([(corners_px[:, 0] - cx) / fx,
                     (corners_px[:, 1] - cy) / fy,
                     np.ones(len(corners_px))], axis=-1)
    denom = rays @ normal
    if np.any(np.abs(denom) < 1e-6):
        return None
    return rays * (-d / denom)[:, None]


def collect(frames_dir, truth, stride=1, limit=None):
    """프레임마다 마커별 코너 3D를 모은다 → {frame_name: {id: (4,3) 배열}}."""
    with open(os.path.join(frames_dir, 'intrinsics.json'), encoding='utf-8') as f:
        intr = json.load(f)
    K = (intr['fx'], intr['fy'], intr['cx'], intr['cy'])
    scale_m = intr.get('depth_scale_m', 0.001)

    det = detector(truth.get('dictionary', 'DICT_5X5_50'))
    images = sorted(glob.glob(os.path.join(frames_dir, 'images', '*.jpg')))[::stride]
    if limit:
        images = images[:limit]

    out = {}
    for path in images:
        name = os.path.basename(path)
        dpath = os.path.join(frames_dir, 'depth', name.replace('.jpg', '.png'))
        if not os.path.exists(dpath):
            continue
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        corners, ids, _ = det.detectMarkers(gray)
        if ids is None:
            continue
        depth = cv2.imread(dpath, cv2.IMREAD_UNCHANGED).astype(np.float64) * scale_m

        found = {}
        for c, i in zip(corners, ids.ravel()):
            p3 = marker_corners_3d(c[0].astype(np.float64), depth, K)
            if p3 is not None:
                found[int(i)] = p3
        if found:
            out[name] = found
    return out, K


def check_depth_accuracy(per_frame, truth, printed_scale=1.0):
    """검증 1 — 한 프레임 안의 마커 중심 거리 vs 인쇄 치수."""
    rows = []
    for name, markers in per_frame.items():
        centers = {i: p.mean(axis=0) for i, p in markers.items()}
        for key, true_mm in truth['pair_mm'].items():
            a, b = (int(x) for x in key.split('-'))
            if a in centers and b in centers:
                meas = np.linalg.norm(centers[a] - centers[b]) * 1000.0
                rows.append((key, true_mm * printed_scale, meas))
    return rows


def check_sfm_scale(per_frame, poses, scale, min_baseline_m=0.05):
    """검증 2 — 같은 마커의 월드 위치가 촬영 지점에 따라 얼마나 벌어지는가.

    (기울기, 절편_mm, 표본수)를 돌려준다. 기울기가 (k-1)/k 이므로
    스케일 오차율 = 기울기 / (1 - 기울기).
    """
    world, cams = {}, {}
    for name, markers in per_frame.items():
        T = poses.get(name)
        if T is None:
            continue
        R, t = T[:3, :3], T[:3, 3] * scale      # SfM 단위 → 미터
        cams[name] = t
        for i, p3 in markers.items():
            world.setdefault(i, {})[name] = (R @ p3.mean(axis=0)) + t

    base, disc = [], []
    for i, obs in world.items():
        names = sorted(obs)
        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                na, nb = names[a], names[b]
                dc = cams[na] - cams[nb]
                bl = np.linalg.norm(dc)
                if bl < min_baseline_m:
                    continue
                # 어긋남을 이동 방향에 투영한다 — 부호가 살아야 과대/과소를 구분한다
                base.append(bl)
                disc.append(float((obs[na] - obs[nb]) @ (dc / bl)))
    if len(base) < 10:
        return None

    b = np.asarray(base)
    d = np.asarray(disc)
    # 이상치에 둔하도록 한 번 다듬는다 (depth가 튄 프레임이 섞일 수 있다)
    keep = np.abs(d - np.median(d)) < 4 * (np.median(np.abs(d - np.median(d))) + 1e-9)
    if keep.sum() > 10:
        b, d = b[keep], d[keep]
    slope, intercept = np.polyfit(b, d, 1)
    return float(slope), float(intercept * 1000.0), int(len(b))


def report(rows, sfm, printed_mm, check_mm):
    print('=' * 62)
    print(' 검증 1 — depth 정확도 (한 프레임 안, SfM과 무관)')
    print('=' * 62)
    if not rows:
        print('  마커 쌍을 한 프레임에서 두 개 이상 본 적이 없다 — 검증 불가')
    else:
        errs = []
        for key in sorted(set(r[0] for r in rows)):
            sel = [r for r in rows if r[0] == key]
            meas = np.array([r[2] for r in sel])
            true_mm = sel[0][1]
            err = (np.median(meas) - true_mm) / true_mm * 100.0
            errs.append(err)
            print('  마커 %s  참값 %6.2fmm  측정 %6.2fmm (중앙값, %d프레임)  오차 %+5.2f%%'
                  % (key, true_mm, np.median(meas), len(sel), err))
        print('  → 종합 오차 %+.2f%% (중앙값)' % float(np.median(errs)))
        if printed_mm != check_mm:
            print('  * 인쇄 배율 %.3f를 반영한 값 (확인선 %.1f→%.1fmm)'
                  % (printed_mm / check_mm, check_mm, printed_mm))

    print()
    print('=' * 62)
    print(' 검증 2 — SfM 스케일 (마커 크기 불필요)')
    print('=' * 62)
    if sfm is None:
        print('  촬영 지점이 충분히 떨어진 관측쌍이 부족하다 — 검증 불가')
        return
    slope, intercept_mm, n = sfm
    err_pct = slope / (1.0 - slope) * 100.0 if abs(1.0 - slope) > 1e-9 else float('nan')
    print('  관측쌍 %d개' % n)
    print('  어긋남 = %+.4f × 촬영거리 + %.1fmm' % (slope, intercept_mm))
    print('  → 스케일 오차 %+.2f%% %s'
          % (err_pct, '(스케일이 크다)' if err_pct > 0 else '(스케일이 작다)'))
    print('  → 노이즈 바닥 %.1fmm (거리와 무관한 성분 — depth 노이즈)' % abs(intercept_mm))
    print()
    print('  읽는 법: 1m 떨어진 두 지점에서 같은 점을 봤을 때 %.0fmm 어긋난다는 뜻.'
          % abs(slope * 1000.0))


def self_test():
    """하드웨어 없이 수식을 검증한다 — 합성 장면으로 참값을 되찾는지 본다."""
    print('자체 검증 — 합성 장면으로 수식이 맞는지 확인한다')
    print('-' * 62)
    rng = np.random.default_rng(0)
    K = (647.0, 646.0, 640.0, 360.0)
    fx, fy, cx, cy = K
    W, H = 1280, 720

    truth = {'dictionary': 'DICT_5X5_50', 'marker_mm': 40.0,
             'pair_mm': {'0-1': 130.0, '0-2': 200.0, '2-3': 130.0}}
    # 마커 중심의 실제 3D 위치 (벽면 z=0.70m, 카메라 정면)
    layout = {0: (-0.065, -0.100), 1: (0.065, -0.100),
              2: (-0.065, 0.100), 3: (0.065, 0.100)}
    half = truth['marker_mm'] / 2000.0
    wall_z = 0.70

    def project(p):
        return np.array([p[0] * fx / p[2] + cx, p[1] * fy / p[2] + cy])

    for label, noise_mm, k in (('깨끗한 장면, 스케일 정확', 0.0, 1.0),
                               ('depth 노이즈 9mm, 스케일 정확', 9.0, 1.0),
                               ('depth 노이즈 9mm, 스케일 +5%', 9.0, 1.05)):
        per_frame, poses, cams = {}, {}, {}
        for fi in range(40):
            # 카메라가 벽과 나란히 좌우로 이동한다
            cam = np.array([(fi - 20) * 0.03, 0.0, 0.0])
            name = 'f%03d.jpg' % fi
            markers = {}
            for mid, (mx, my) in layout.items():
                corners_w = np.array([[mx - half, my - half, wall_z],
                                      [mx + half, my - half, wall_z],
                                      [mx + half, my + half, wall_z],
                                      [mx - half, my + half, wall_z]])
                cam_pts = corners_w - cam
                px = np.array([project(p) for p in cam_pts])
                if px.min() < 0 or px[:, 0].max() > W or px[:, 1].max() > H:
                    continue
                # 평면 맞춤이 노이즈를 평균내는 효과를 모사: 코너당 잔여 노이즈를
                # 1/sqrt(내부픽셀수) 수준으로 줄여 넣는다
                z = wall_z + rng.normal(0, noise_mm / 1000.0 / np.sqrt(300))
                rays = np.stack([(px[:, 0] - cx) / fx, (px[:, 1] - cy) / fy,
                                 np.ones(4)], axis=-1)
                markers[mid] = rays * (z / 1.0)
            if markers:
                per_frame[name] = markers
                # 포즈는 SfM 단위(= 미터 / scale_true). 복원 스케일이 k배 틀렸다고 두면
                # 월드 변환에 쓰이는 t가 k배가 된다
                T = np.eye(4)
                T[:3, 3] = cam * k
                poses[name] = T
                cams[name] = cam
        rows = check_depth_accuracy(per_frame, truth)
        sfm = check_sfm_scale(per_frame, poses, scale=1.0)
        derr = np.median([(r[2] - r[1]) / r[1] * 100 for r in rows])
        serr = sfm[0] / (1 - sfm[0]) * 100 if sfm else float('nan')
        print('%-28s  depth오차 %+6.2f%%   스케일오차 %+6.2f%%  (참값 %+.0f%%)'
              % (label, derr, serr, (k - 1) * 100))
    print('-' * 62)
    print('세 줄 모두 참값과 맞으면 수식이 맞는 것이다.')


def main():
    ap = argparse.ArgumentParser(description='인쇄 타겟으로 depth/SfM 스케일 검증')
    ap.add_argument('--frames', help='추출된 프레임 디렉토리')
    ap.add_argument('--truth', help='make_scale_target.py가 남긴 참값 JSON')
    ap.add_argument('--poses', help='COLMAP images.txt (검증 2에 필요)')
    ap.add_argument('--scale', type=float, help='복원된 스케일 (검증 2에 필요)')
    ap.add_argument('--printed-mm', type=float,
                    help='인쇄된 확인선을 자로 잰 실제 길이(mm). 생략하면 100%% 인쇄로 본다')
    ap.add_argument('--stride', type=int, default=1, help='N장에 1장만 본다')
    ap.add_argument('--limit', type=int, help='앞에서 N장만 본다(빠른 확인용)')
    ap.add_argument('--self-test', action='store_true',
                    help='하드웨어 없이 수식만 검증한다')
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.frames or not args.truth:
        ap.error('--frames 와 --truth 가 필요합니다 (또는 --self-test)')

    with open(args.truth, encoding='utf-8') as f:
        truth = json.load(f)
    check_mm = truth.get('check_line_mm', 160.0)
    printed_mm = args.printed_mm or check_mm
    printed_scale = printed_mm / check_mm

    per_frame, _ = collect(args.frames, truth, args.stride, args.limit)
    n_markers = sum(len(v) for v in per_frame.values())
    print('마커를 본 프레임 %d장, 관측 %d건' % (len(per_frame), n_markers))
    if not per_frame:
        raise SystemExit('타겟을 한 번도 찾지 못했다 — 타겟이 찍혔는지, '
                         '딕셔너리(%s)가 맞는지 확인할 것' % truth.get('dictionary'))

    rows = check_depth_accuracy(per_frame, truth, printed_scale)

    sfm = None
    if args.poses and args.scale:
        poses = read_colmap_images(args.poses)
        sfm = check_sfm_scale(per_frame, poses, args.scale)
    print()
    report(rows, sfm, printed_mm, check_mm)
    if not (args.poses and args.scale):
        print()
        print('(검증 2를 하려면 --poses 와 --scale 을 함께 줄 것)')


if __name__ == '__main__':
    main()
