#!/usr/bin/env python3
"""재구성 결과의 정합 품질을 평면 두께로 정량화한다.

2026-08-20에 고스팅(같은 표면이 여러 겹으로 어긋나 쌓이는 현상)을 확인할 때 쓴
측정을 스크립트로 고정한 것 — 그땐 일회성 코드였고 남아있지 않아서, 앞으로
재구성 방식을 바꿔가며 같은 기준으로 비교하려면 스크립트가 필요하다.

원리: 가장 큰 평면을 RANSAC으로 찾고, 그 평면까지의 부호 있는 거리 분포를 본다.
정합이 완벽하면 센서 노이즈만 남아 봉우리가 하나인 정규분포에 가깝고, 같은 면이
여러 겹으로 어긋나 쌓이면 봉우리가 여러 개로 갈린다.

2026-08-20 벽 스캔 기준값(이 스크립트가 재현해야 하는 값):
    rtabmap-export 기본        봉우리 2개(간격 26mm), σ 29.3mm
    rtabmap-export --ba        봉우리 1개,            σ 20.7mm
"""

import numpy as np


def fit_plane_ransac(points, threshold_m=0.02, iterations=1000, seed=0):
    """점군에서 가장 큰 평면을 찾아 (법선, 원점거리, 인라이어 마스크)를 돌려준다.

    평면은 `normal · p + d = 0` 형태이고 normal은 단위벡터로 정규화한다.
    threshold_m는 인라이어 판정 거리 — 기본 2cm는 D455F의 1m 거리 depth 노이즈
    (σ 약 20mm)를 한 겹 감싸는 값이라, 고스팅으로 갈라진 겹들을 하나의 평면
    후보로 함께 잡아 두께를 재려는 의도다(너무 좁히면 겹 하나만 잡혀서
    고스팅이 안 보인다).
    """
    points = np.asarray(points, dtype=np.float64)
    if points.shape[0] < 3:
        raise ValueError('평면을 맞추려면 점이 최소 3개 필요하다')

    rng = np.random.default_rng(seed)
    best_inliers = None
    best_count = -1

    for _ in range(iterations):
        idx = rng.choice(points.shape[0], size=3, replace=False)
        p0, p1, p2 = points[idx]
        normal = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(normal)
        if norm < 1e-12:
            continue  # 세 점이 일직선 — 평면이 정의되지 않는다
        normal = normal / norm
        d = -float(normal @ p0)
        dist = np.abs(points @ normal + d)
        inliers = dist < threshold_m
        count = int(inliers.sum())
        if count > best_count:
            best_count, best_inliers = count, inliers

    if best_inliers is None:
        raise RuntimeError('평면을 찾지 못했다(점이 모두 일직선일 수 있음)')

    # RANSAC이 고른 3점은 잡음이 섞여 있으므로, 인라이어 전체에 최소제곱을 다시
    # 맞춰 평면을 정밀화한다(법선 = 공분산의 최소 고유벡터).
    inlier_pts = points[best_inliers]
    centroid = inlier_pts.mean(axis=0)
    _, _, vh = np.linalg.svd(inlier_pts - centroid, full_matrices=False)
    normal = vh[-1]
    normal = normal / np.linalg.norm(normal)
    d = -float(normal @ centroid)
    return normal, d, best_inliers


def refine_plane(points, normal, d, band_m=0.10, iterations=3):
    """측정 구간 안의 점 전체로 평면 방향을 다시 맞춘다(총최소제곱).

    왜 필요한가(개발 중 실제로 밟은 함정): RANSAC은 인라이어 **개수**를 최대화하므로,
    판정 거리가 고스팅 간격과 비슷하면 평면을 살짝 기울여서 어긋난 두 겹을 한꺼번에
    인라이어로 삼켜버린다. 합성 실험에서 26mm 간격의 두 겹(각 11,360점)을 20mm
    임계값으로 맞추자 0.85° 기울어진 평면이 17,680점을 인라이어로 잡았고, 그 결과
    두 봉우리가 연속 분포로 뭉개져 **고스팅이 측정에서 사라졌다**.

    그래서 RANSAC은 "어느 점들이 주 표면인가"를 고르는 데만 쓰고, 평면의 방향은
    구간 안의 점 전체에 대한 총최소제곱으로 다시 정한다. 겹이 나란히 어긋난
    경우(평행 이동 오차) 전체의 최적 방향은 겹들의 평균 방향이 되므로, 두 겹이
    분포의 양쪽 봉우리로 제대로 남는다.
    """
    points = np.asarray(points, dtype=np.float64)
    for _ in range(iterations):
        dist = points @ normal + d
        sel = points[np.abs(dist) < band_m]
        if sel.shape[0] < 3:
            break
        centroid = sel.mean(axis=0)
        _, _, vh = np.linalg.svd(sel - centroid, full_matrices=False)
        new_normal = vh[-1] / np.linalg.norm(vh[-1])
        if new_normal @ normal < 0:   # 방향 뒤집힘 방지
            new_normal = -new_normal
        normal, d = new_normal, -float(new_normal @ centroid)
    return normal, d


def signed_distances(points, normal, d):
    """각 점의 평면까지의 부호 있는 거리(m)."""
    return np.asarray(points, dtype=np.float64) @ np.asarray(normal, dtype=np.float64) + d


def count_peaks(dists_m, bin_width_m=None, valley_ratio=0.85, min_height_ratio=0.25):
    """부호 있는 거리 히스토그램에서 뚜렷한 봉우리 개수를 센다.

    고스팅이면 봉우리가 여러 개로 갈린다. 문제는 아무리 매끈한 단봉 분포라도
    표본 잡음 때문에 히스토그램 꼭대기가 잘게 울퉁불퉁해져서, 단순히 극대점을
    세면 봉우리가 여러 개로 나온다는 것 — 그래서 **봉우리 사이의 골이 얼마나
    깊은지**(prominence)로 판정한다. 두 극대점 사이의 최소값이 두 봉우리 중
    낮은 쪽의 valley_ratio배보다 높으면, 둘은 갈라진 게 아니라 한 봉우리 위의
    잔물결로 보고 병합한다.

    bin_width_m을 안 주면 분포 폭에 맞춰 자동으로 정한다(약 60개 구간) —
    σ가 5mm일 때와 30mm일 때 같은 고정 폭을 쓰면 한쪽은 과하게 거칠고
    다른 쪽은 과하게 잘게 나뉘기 때문.
    """
    dists_m = np.asarray(dists_m, dtype=np.float64)
    span = float(dists_m.max() - dists_m.min())
    if span <= 0 or dists_m.size < 10:
        return 1, np.array([float(dists_m.mean()) if dists_m.size else 0.0])

    if bin_width_m is None:
        bin_width_m = span / 60.0
    bins = np.arange(dists_m.min(), dists_m.max() + bin_width_m, bin_width_m)
    if len(bins) < 5:
        return 1, np.array([float(dists_m.mean())])
    hist, edges = np.histogram(dists_m, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0

    # 구간 수에 비례한 이동평균으로 잔물결을 눌러준다(구간 폭이 적응적이므로
    # 커널도 개수 기준으로 잡아야 분포 폭에 무관하게 같은 정도로 매끈해진다).
    k = max(3, (len(hist) // 12) * 2 + 1)
    hist = np.convolve(hist.astype(np.float64), np.ones(k) / k, mode='same')

    # 양 끝에 0을 덧대고 극대점을 찾는다 — 이렇게 안 하면 분포의 **맨 끝에 있는
    # 봉우리**가 후보에서 빠진다(두 겹이 완전히 갈라져 히스토그램 양 끝에 몰리는
    # 경우가 정확히 그 상황이라, 정작 가장 심한 고스팅을 놓치게 된다).
    padded = np.concatenate(([0.0], hist, [0.0]))
    peak_idx = [i - 1 for i in range(1, len(padded) - 1)
                if padded[i] >= padded[i - 1] and padded[i] > padded[i + 1]
                and padded[i] >= hist.max() * min_height_ratio]
    if not peak_idx:
        return 1, np.array([float(centers[int(np.argmax(hist))])])

    # 골이 얕은 이웃 봉우리끼리 반복적으로 병합
    changed = True
    while changed and len(peak_idx) > 1:
        changed = False
        for a, b in zip(peak_idx, peak_idx[1:]):
            valley = hist[a:b + 1].min()
            if valley > min(hist[a], hist[b]) * valley_ratio:
                peak_idx.remove(a if hist[a] < hist[b] else b)
                changed = True
                break

    return len(peak_idx), centers[np.array(peak_idx)]


def analyse(points, threshold_m=0.02, band_m=0.10, seed=0):
    """점군 하나에 대한 정합 품질 요약.

    threshold_m와 band_m을 나눠 쓰는 이유(중요):
      threshold_m는 **평면을 찾을 때만** 쓰는 RANSAC 인라이어 판정 거리다. 이걸
      그대로 두께 측정에도 쓰면 분포의 꼬리가 잘려나가 σ가 실제보다 작게 나온다
      (노이즈 σ 15mm인 합성 점군을 20mm로 자르면 σ가 10mm로 측정됨 — 유닛
      테스트로 확인). 그래서 평면을 찾은 뒤에는 훨씬 넓은 band_m(기본 ±100mm)
      안의 점을 모아 두께를 잰다. band_m 밖은 다른 벽이나 잡물이라 빼는 게 맞다.
    """
    points = np.asarray(points, dtype=np.float64)
    normal, d, _ = fit_plane_ransac(points, threshold_m=threshold_m, seed=seed)
    # RANSAC 평면은 기울어서 고스팅을 삼킬 수 있으므로 방향을 다시 맞춘다
    normal, d = refine_plane(points, normal, d, band_m=band_m)

    all_dist = signed_distances(points, normal, d)
    in_band = np.abs(all_dist) < band_m
    dists = all_dist[in_band]
    if dists.size < 10:
        raise RuntimeError('측정 구간(±%.0fmm) 안에 점이 너무 적다' % (band_m * 1000))

    n_peaks, peak_positions = count_peaks(dists)
    spread_mm = 0.0
    if n_peaks > 1:
        spread_mm = float((peak_positions.max() - peak_positions.min()) * 1000.0)
    return {
        'total_points': int(points.shape[0]),
        'plane_points': int(in_band.sum()),
        'sigma_mm': float(dists.std() * 1000.0),
        'peaks': int(n_peaks),
        'peak_positions_mm': (peak_positions * 1000.0).tolist(),
        'peak_spread_mm': spread_mm,
        'normal': normal.tolist(),
    }


def _load_ply(path):
    """PLY(ascii/binary_little_endian)에서 xyz만 읽는다.

    rtabmap-export와 Open3D가 내놓는 형식을 읽으려는 최소 구현 — 외부 의존성
    없이 이 스크립트만으로 평가가 돌아가게 하려는 의도다.
    """
    with open(path, 'rb') as f:
        if f.readline().strip() != b'ply':
            raise ValueError('PLY 파일이 아니다: %s' % path)
        fmt = None
        count = None
        props = []
        while True:
            line = f.readline()
            if not line:
                raise ValueError('헤더가 끝나기 전에 파일이 끝났다')
            parts = line.split()
            if not parts:
                continue
            key = parts[0]
            if key == b'format':
                fmt = parts[1].decode()
            elif key == b'element' and parts[1] == b'vertex':
                count = int(parts[2])
            elif key == b'property' and count is not None and len(parts) == 3:
                props.append((parts[1].decode(), parts[2].decode()))
            elif key == b'end_header':
                break

        names = [n for _, n in props]
        for axis in ('x', 'y', 'z'):
            if axis not in names:
                raise ValueError('PLY에 %s 속성이 없다' % axis)

        if fmt == 'ascii':
            data = np.loadtxt(f, max_rows=count, ndmin=2)
            cols = [names.index(a) for a in ('x', 'y', 'z')]
            return data[:, cols]

        if fmt != 'binary_little_endian':
            raise ValueError('지원하지 않는 PLY 형식: %s' % fmt)

        np_types = {'float': 'f4', 'float32': 'f4', 'double': 'f8', 'float64': 'f8',
                    'uchar': 'u1', 'uint8': 'u1', 'char': 'i1', 'int8': 'i1',
                    'ushort': 'u2', 'uint16': 'u2', 'short': 'i2', 'int16': 'i2',
                    'uint': 'u4', 'uint32': 'u4', 'int': 'i4', 'int32': 'i4'}
        dtype = np.dtype([(n, '<' + np_types[t]) for t, n in props])
        arr = np.frombuffer(f.read(dtype.itemsize * count), dtype=dtype, count=count)
        return np.stack([arr['x'], arr['y'], arr['z']], axis=1).astype(np.float64)


def main():
    import argparse
    import json

    ap = argparse.ArgumentParser(description='재구성 결과의 평면 두께로 정합 품질을 잰다')
    ap.add_argument('ply', help='측정할 포인트클라우드(.ply)')
    ap.add_argument('--threshold-mm', type=float, default=20.0,
                    help='평면을 찾을 때의 RANSAC 인라이어 거리(mm, 기본 20)')
    ap.add_argument('--band-mm', type=float, default=100.0,
                    help='두께를 잴 구간(±mm, 기본 100) — 이걸 좁히면 σ가 잘려 작게 나온다')
    ap.add_argument('--max-points', type=int, default=300000,
                    help='이보다 많으면 무작위로 솎아낸다(속도)')
    ap.add_argument('--json', action='store_true', help='JSON으로 출력')
    args = ap.parse_args()

    pts = _load_ply(args.ply)
    if pts.shape[0] > args.max_points:
        rng = np.random.default_rng(0)
        pts = pts[rng.choice(pts.shape[0], args.max_points, replace=False)]

    result = analyse(pts, threshold_m=args.threshold_mm / 1000.0,
                     band_m=args.band_mm / 1000.0)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('점 개수        : %d (측정 구간 안 %d)' % (result['total_points'], result['plane_points']))
        print('평면 두께 σ    : %.1f mm' % result['sigma_mm'])
        print('봉우리 개수    : %d' % result['peaks'])
        if result['peaks'] > 1:
            print('봉우리 위치    : %s mm' % ', '.join('%.1f' % p for p in result['peak_positions_mm']))
            print('봉우리 간격    : %.1f mm  ← 고스팅' % result['peak_spread_mm'])


if __name__ == '__main__':
    main()
