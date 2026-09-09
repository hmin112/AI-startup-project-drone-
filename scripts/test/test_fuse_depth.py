"""fuse_depth.py 유닛 테스트 — 합성 장면으로 검증.

실행: `pytest scripts/test/` (numpy만 필요, ROS/하드웨어/COLMAP 불필요).

A안의 전제가 "포즈 오차가 고스팅의 주범"이므로, 이 테스트의 핵심은 마지막
test_pose_error_produces_measurable_ghosting — **포즈에 일부러 오차를 주입하면
plane_sigma가 그만큼의 고스팅을 실제로 검출하는지** 확인한다. 이게 되면
측정 장치(융합 + 지표)가 가설을 검증할 능력이 있다는 뜻이다.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fuse_depth import (  # noqa: E402
    deproject,
    estimate_scale_from_sparse,
    quat_to_rotation,
    read_colmap_images,
    read_tum_poses,
    transform,
    write_ply,
)
from plane_sigma import _load_ply, analyse  # noqa: E402

FX = FY = 428.0   # 848x480에서의 실측 초점거리(1280 기준 646을 848로 환산)
CX, CY = 424.0, 240.0
W, H = 848, 480


def test_quat_to_rotation_identity_and_90deg():
    assert np.allclose(quat_to_rotation(1, 0, 0, 0), np.eye(3))
    # z축 90도 회전: x축이 y축으로 간다
    r = quat_to_rotation(np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4))
    assert np.allclose(r @ np.array([1.0, 0, 0]), [0, 1, 0], atol=1e-9)


def test_colmap_pose_is_inverted_to_camera_to_world(tmp_path):
    """COLMAP은 world→camera로 저장하므로 읽을 때 뒤집혀야 한다.

    카메라를 world의 (1, 2, 3)에 회전 없이 둔다. 그러면 world→camera는
    R=I, T=-(1,2,3)이고, 우리가 읽어낸 camera→world의 이동은 (1,2,3)이어야 한다.
    뒤집기를 빼먹으면 부호가 반대로 나와 이 테스트가 잡아낸다.
    """
    p = tmp_path / 'images.txt'
    p.write_text('# comment\n1 1 0 0 0 -1 -2 -3 1 frame_000001.jpg\n'
                 '100.0 200.0 -1\n', encoding='utf-8')
    poses = read_colmap_images(str(p))
    assert list(poses) == ['frame_000001.jpg']
    m = poses['frame_000001.jpg']
    assert np.allclose(m[:3, :3], np.eye(3))
    assert np.allclose(m[:3, 3], [1.0, 2.0, 3.0])


def test_tum_poses_are_not_inverted(tmp_path):
    """TUM 형식은 이미 camera→world라 그대로 써야 한다."""
    p = tmp_path / 'poses.txt'
    p.write_text('# ts tx ty tz qx qy qz qw\n1.5 1 2 3 0 0 0 1\n', encoding='utf-8')
    m = read_tum_poses(str(p))['1.5']
    assert np.allclose(m[:3, 3], [1.0, 2.0, 3.0])
    assert np.allclose(m[:3, :3], np.eye(3))


def test_deproject_constant_depth_gives_flat_plane():
    """일정한 depth 이미지는 카메라 앞 그 거리의 평면이 돼야 한다."""
    depth = np.full((H, W), 1.2)
    pts = deproject(depth, FX, FY, CX, CY, stride=8)
    assert pts.shape[0] > 1000
    assert np.allclose(pts[:, 2], 1.2)
    # 주점(cx, cy) 픽셀은 광학축 위이므로 x=y=0
    center = deproject(np.full((1, 1), 1.2), FX, FY, 0.0, 0.0, stride=1)
    assert np.allclose(center[0], [0.0, 0.0, 1.2])


def test_deproject_filters_invalid_range():
    """유효 거리 밖(무효 depth 0 포함)은 버려야 한다."""
    depth = np.zeros((10, 10))
    depth[0, 0] = 1.0    # 유효
    depth[0, 1] = 5.0    # 너무 멂
    depth[0, 2] = 0.1    # 너무 가까움
    assert deproject(depth, FX, FY, CX, CY, min_m=0.3, max_m=3.0).shape[0] == 1


def _plane_depth_image(distance_m=1.0):
    """카메라 정면 distance_m에 있는 벽을 본 depth 이미지(픽셀별 실제 거리 아님, z값)."""
    return np.full((H, W), distance_m)


def test_scale_recovered_from_depth(tmp_path):
    """SfM 좌표가 임의 배율로 축소돼 있어도 depth로 실제 크기를 되찾아야 한다."""
    true_scale = 3.7
    # SfM 좌표계: 카메라 원점, 점들은 z=1/true_scale 부근에 흩어져 있다
    # (실제로는 z=1.0m인데 SfM 단위가 작다는 상황)
    n = 60
    rng = np.random.default_rng(0)
    ids = list(range(1, n + 1))
    z_sfm = 1.0 / true_scale
    pts = tmp_path / 'points3D.txt'
    pts.write_text('# 3D points\n' + '\n'.join(
        '%d %f %f %f 0 0 0 0.5' % (i, rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), z_sfm)
        for i in ids), encoding='utf-8')

    obs = ' '.join('%f %f %d' % (100 + i, 200, i) for i in ids)
    imgs = tmp_path / 'images.txt'
    imgs.write_text('1 1 0 0 0 0 0 0 1 frame.jpg\n' + obs + '\n', encoding='utf-8')

    scale, used, _ = estimate_scale_from_sparse(
        str(pts), str(imgs), lambda name, u, v: 1.0)  # 측정 depth는 전부 1.0m
    assert used == n
    assert scale == pytest.approx(true_scale, rel=0.02)


def test_scale_estimate_resists_outliers(tmp_path):
    """depth 무효/오매칭으로 튀는 값이 섞여도 중앙값이라 버텨야 한다."""
    n = 60
    z_sfm = 0.5
    ids = list(range(1, n + 1))
    pts = tmp_path / 'points3D.txt'
    pts.write_text('\n'.join('%d 0 0 %f 0 0 0 0.5' % (i, z_sfm) for i in ids), encoding='utf-8')
    obs = ' '.join('%f %f %d' % (10, 10, i) for i in ids)
    imgs = tmp_path / 'images.txt'
    imgs.write_text('1 1 0 0 0 0 0 0 1 f.jpg\n' + obs + '\n', encoding='utf-8')

    def lookup(name, u, v, _c=[0]):
        _c[0] += 1
        return 50.0 if _c[0] % 6 == 0 else 1.0  # 6개 중 1개는 말도 안 되는 값

    scale, _, _ = estimate_scale_from_sparse(str(pts), str(imgs), lookup)
    assert scale == pytest.approx(2.0, rel=0.05)  # 1.0 / 0.5, 이상값에 안 흔들림


def test_ply_roundtrip(tmp_path):
    pts = np.random.default_rng(1).uniform(-1, 1, (500, 3))
    out = tmp_path / 'c.ply'
    write_ply(str(out), pts)
    assert np.allclose(_load_ply(str(out)), pts, atol=1e-5)


def _two_view_cloud(pose_offset_m=0.0):
    """같은 벽을 두 위치에서 본 뒤 쌓는다. pose_offset_m만큼 두 번째 포즈를 틀어준다.

    카메라는 z축(광학축)이 벽을 향하므로, 두 번째 카메라를 z로 밀면 재구성된
    벽이 그만큼 어긋나 쌓인다 — 실제 궤적 오차가 만드는 고스팅과 같은 형태.
    """
    depth = _plane_depth_image(1.0)
    pts = deproject(depth, FX, FY, CX, CY, stride=6)

    m1 = np.eye(4)                      # 첫 번째 카메라: world 원점
    m2 = np.eye(4)
    m2[2, 3] = 0.30                     # 실제로는 30cm 옆으로 이동
    m2_err = m2.copy()
    m2_err[2, 3] += pose_offset_m       # 포즈 추정 오차

    # 두 번째 뷰가 보는 벽은 실제로 30cm 더 가까우므로 depth도 그만큼 줄어든다
    depth2 = _plane_depth_image(1.0 - 0.30)
    pts2 = deproject(depth2, FX, FY, CX, CY, stride=6)

    return np.vstack([transform(pts, m1), transform(pts2, m2_err)])


def test_perfect_poses_reconstruct_a_single_thin_plane():
    """포즈가 정확하면 두 뷰가 완전히 겹쳐 두께 0의 평면이 나와야 한다."""
    cloud = _two_view_cloud(pose_offset_m=0.0)
    r = analyse(cloud)
    assert r['peaks'] == 1
    assert r['sigma_mm'] < 1.0


def test_pose_error_produces_measurable_ghosting():
    """포즈에 26mm 오차를 주면 고스팅이 26mm 간격의 두 봉우리로 검출돼야 한다.

    이게 A안 실험의 핵심 장치다 — 8/20 벽 스캔에서 관측된 "봉우리 2개, 간격
    26mm"와 같은 형태를 포즈 오차만으로 만들 수 있음을 보인다. 즉 융합 코드와
    평가 지표가 포즈 오차를 실제로 잡아낼 수 있다는 확인.
    """
    cloud = _two_view_cloud(pose_offset_m=0.026)
    r = analyse(cloud)
    assert r['peaks'] == 2
    assert r['peak_spread_mm'] == pytest.approx(26.0, abs=4.0)


def test_pose_error_ghosting_with_realistic_noise():
    """실제 depth 노이즈가 섞여도 포즈 오차로 인한 고스팅이 보여야 한다.

    위 테스트는 노이즈 0인 이상적 상황이고, 이건 겹마다 σ 5mm의 노이즈를 준
    현실적인 경우 — 실제 스캔에 더 가깝다.
    """
    rng = np.random.default_rng(3)
    cloud = _two_view_cloud(pose_offset_m=0.026)
    cloud[:, 2] += rng.normal(0.0, 0.005, cloud.shape[0])
    r = analyse(cloud)
    assert r['peaks'] == 2
    assert r['peak_spread_mm'] == pytest.approx(26.0, abs=5.0)
