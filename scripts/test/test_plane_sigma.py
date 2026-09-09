"""plane_sigma.py 유닛 테스트 — 합성 점군으로 지표가 맞는 값을 내는지 확인.

실행: `pytest scripts/test/` (numpy만 필요, ROS/하드웨어 불필요).

이 지표는 재구성 방식을 바꿔가며 비교할 때의 기준자이므로, 자 자체가 정확한지
먼저 확인해둔다 — 정답을 아는 합성 점군(노이즈 σ와 겹 간격을 직접 지정)으로
검증한다.
"""
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plane_sigma import (  # noqa: E402
    _load_ply,
    analyse,
    count_peaks,
    fit_plane_ransac,
    signed_distances,
)


def _plane_points(n=8000, sigma_m=0.02, normal=(0.0, 0.0, 1.0), offset_m=0.0, seed=0):
    """지정한 법선의 평면 위에 노이즈를 준 점군을 만든다."""
    rng = np.random.default_rng(seed)
    normal = np.array(normal, dtype=np.float64)
    normal /= np.linalg.norm(normal)
    # 법선에 직교하는 두 축을 만들어 평면 위에 점을 뿌린다
    tmp = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(normal, tmp); u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    a = rng.uniform(-1.0, 1.0, n)
    b = rng.uniform(-1.0, 1.0, n)
    noise = rng.normal(0.0, sigma_m, n)
    return (a[:, None] * u + b[:, None] * v
            + (offset_m + noise)[:, None] * normal)


def test_clean_plane_recovers_noise_sigma():
    """겹침이 없는 평면 하나면 봉우리 1개, σ는 준 노이즈와 일치해야 한다."""
    pts = _plane_points(sigma_m=0.020, seed=1)
    r = analyse(pts)
    assert r['peaks'] == 1
    assert r['sigma_mm'] == pytest.approx(20.0, abs=2.0)


def test_ghosting_two_layers_is_detected():
    """같은 면이 26mm 어긋나 두 겹으로 쌓이면 봉우리가 2개로 갈려야 한다.

    2026-08-20 벽 스캔에서 실제로 관측된 상황(봉우리 2개, 간격 26mm)을 합성으로
    재현한 것 — 그때 σ 20.7mm로 병합된 것과 대비된다.
    """
    layer_sigma = 0.008  # 겹 하나의 두께를 얇게 줘야 두 봉우리가 분리돼 보인다
    a = _plane_points(n=5000, sigma_m=layer_sigma, offset_m=-0.013, seed=2)
    b = _plane_points(n=5000, sigma_m=layer_sigma, offset_m=+0.013, seed=3)
    r = analyse(np.vstack([a, b]))
    assert r['peaks'] == 2
    assert r['peak_spread_mm'] == pytest.approx(26.0, abs=6.0)


def test_merged_layers_look_like_single_peak():
    """번들 조정으로 두 겹이 하나로 병합되면 다시 봉우리 1개가 돼야 한다."""
    merged = _plane_points(n=10000, sigma_m=0.0207, seed=4)
    r = analyse(merged)
    assert r['peaks'] == 1
    assert r['sigma_mm'] == pytest.approx(20.7, abs=2.0)


def test_tilted_plane_gives_same_sigma():
    """평면이 축에 정렬돼 있지 않아도 결과가 같아야 한다(법선 추정이 제대로 되는지)."""
    pts = _plane_points(sigma_m=0.015, normal=(0.4, -0.5, 0.77), seed=5)
    r = analyse(pts)
    assert r['peaks'] == 1
    assert r['sigma_mm'] == pytest.approx(15.0, abs=2.0)


def test_fit_plane_finds_dominant_plane_among_outliers():
    """벽이 아닌 점(바닥/물체)이 섞여 있어도 가장 큰 평면을 골라야 한다."""
    wall = _plane_points(n=8000, sigma_m=0.01, seed=6)
    rng = np.random.default_rng(7)
    clutter = rng.uniform(-1.0, 1.0, (2000, 3)) + np.array([0.0, 0.0, 1.5])
    normal, d, inliers = fit_plane_ransac(np.vstack([wall, clutter]), threshold_m=0.03)
    # 인라이어는 벽 쪽(앞 8000개)에 몰려야 한다
    assert inliers[:8000].sum() > 7000
    assert inliers[8000:].sum() < 600
    assert abs(abs(normal[2]) - 1.0) < 0.05  # 법선이 z축에 가까움


def test_signed_distances_sign_is_consistent():
    """평면 양쪽 점의 부호가 반대로 나와야 한다."""
    normal = np.array([0.0, 0.0, 1.0])
    pts = np.array([[0.0, 0.0, 0.05], [0.0, 0.0, -0.05]])
    dist = signed_distances(pts, normal, 0.0)
    assert dist[0] > 0 and dist[1] < 0


def test_count_peaks_on_flat_distribution():
    """분포가 아주 좁으면(전부 같은 값) 봉우리 1개로 처리돼야 한다."""
    n_peaks, positions = count_peaks(np.zeros(100))
    assert n_peaks == 1
    assert len(positions) == 1


def _write_ply(path, points, binary):
    header = ['ply',
              'format %s 1.0' % ('binary_little_endian' if binary else 'ascii'),
              'element vertex %d' % len(points),
              'property float x', 'property float y', 'property float z',
              'end_header', '']
    with open(path, 'wb') as f:
        f.write('\n'.join(header).encode())
        if binary:
            for p in points:
                f.write(struct.pack('<fff', *p))
        else:
            for p in points:
                f.write(('%f %f %f\n' % tuple(p)).encode())


def test_load_ply_ascii_and_binary_match(tmp_path):
    """ascii/binary 두 형식을 같은 값으로 읽어야 한다(rtabmap-export는 binary를 낸다)."""
    pts = _plane_points(n=200, sigma_m=0.01, seed=8)
    a, b = tmp_path / 'a.ply', tmp_path / 'b.ply'
    _write_ply(a, pts, binary=False)
    _write_ply(b, pts, binary=True)
    la, lb = _load_ply(str(a)), _load_ply(str(b))
    assert la.shape == pts.shape == lb.shape
    assert np.allclose(la, lb, atol=1e-5)
    assert np.allclose(lb, pts, atol=1e-5)


def test_measurement_band_must_not_truncate_sigma():
    """측정 구간을 좁게 잡으면 σ가 작게 나오는 편향이 있다 — 기본값이 안전한지 확인.

    개발 중 실제로 밟은 함정: 평면을 찾는 RANSAC 임계값(20mm)을 두께 측정에도
    그대로 쓰면 분포 꼬리가 잘려 σ 15mm가 10mm로 측정됐다. 재구성 방식 A/B에서
    이런 편향이 있으면 노이즈가 큰 쪽이 오히려 좋아 보이는 역전이 생기므로,
    기본 구간(±100mm)에서는 편향이 없어야 한다.
    """
    pts = _plane_points(n=20000, sigma_m=0.030, seed=11)
    assert analyse(pts)['sigma_mm'] == pytest.approx(30.0, abs=3.0)
    # 구간을 좁히면 실제로 작게 나오는 것도 함께 확인(원인이 이것임을 고정)
    assert analyse(pts, band_m=0.02)['sigma_mm'] < 20.0
