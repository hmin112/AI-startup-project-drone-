"""verify_scale.py 유닛 테스트 — 합성 장면에서 참값을 되찾는지 확인.

실행: `pytest scripts/test/` (numpy/opencv만 필요, 하드웨어 불필요).

**왜 합성 장면까지 만드는가.** 이 스크립트는 "재구성 치수가 맞느냐"에 답하는
물건이다. 그 답이 틀리면 뒤의 모든 치수를 틀린 채로 신뢰하게 되므로, 검증기
자체를 먼저 검증해야 한다. 수식만 보는 테스트로는 영상 쪽 실수를 못 잡는다 —
실제로 여기서 **렌더러가 상하를 뒤집어 마커를 거울상으로 그리던 버그**가
잡혔다(ArUco가 거울상을 거부해 한 장도 안 읽혔다). 그래서 인쇄 타겟 PNG를
실제로 투영해 JPEG으로 굽고, 검출기부터 평면맞춤·시선교차까지 전 경로를 돌린다.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_scale_target import main as make_target_main  # noqa: E402
import verify_scale  # noqa: E402


W, H = 1280, 720
INTR = {'fx': 647.0, 'fy': 646.0, 'cx': 640.0, 'cy': 360.0,
        'width': W, 'height': H, 'depth_scale_m': 0.001}
PX_PER_MM = 300 / 25.4
WALL_Z = 0.70           # 목표 대역(0.6~0.8m) 한가운데
N_FRAMES = 30


def _render_scan(out_dir, target_png, noise_mm=9.0, seed=1):
    """인쇄 타겟이 벽에 붙어 있고 카메라가 좌우로 지나가는 장면을 렌더한다."""
    rng = np.random.default_rng(seed)
    tgt = cv2.imread(str(target_png), cv2.IMREAD_GRAYSCALE)
    th, tw = tgt.shape
    fx, fy, cx, cy = INTR['fx'], INTR['fy'], INTR['cx'], INTR['cy']

    # 벽을 살짝 기울여 둔다 — 정면 평면만 맞으면 평면맞춤이 검증되지 않는다
    n = np.array([0.08, 0.05, -1.0])
    n /= np.linalg.norm(n)
    p0 = np.array([0.0, 0.0, WALL_Z])
    d = -n @ p0
    u = np.cross(n, [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    # 이미지 y축은 아래를 향한다. cross(n, u)로 두면 상하가 뒤집혀 마커가
    # 거울상이 되고 ArUco가 전부 거부한다 — 반사는 회전으로 복구되지 않는다.
    v = np.cross(u, n)

    def target_px_to_world(p):
        mx = (p[0] - tw / 2) / PX_PER_MM / 1000.0
        my = (p[1] - th / 2) / PX_PER_MM / 1000.0
        return p0 + u * mx + v * my

    (out_dir / 'images').mkdir(parents=True, exist_ok=True)
    (out_dir / 'depth').mkdir(parents=True, exist_ok=True)
    (out_dir / 'intrinsics.json').write_text(json.dumps(INTR), encoding='utf-8')

    uu, vv = np.meshgrid(np.arange(W), np.arange(H))
    rays = np.stack([(uu - cx) / fx, (vv - cy) / fy, np.ones_like(uu, float)], -1)
    src = np.float32([[0, 0], [tw - 1, 0], [tw - 1, th - 1], [0, th - 1]])

    cams = {}
    for fi in range(N_FRAMES):
        cam = np.array([(fi - N_FRAMES / 2) * 0.025, 0.0, 0.0])
        dst = []
        for p in src:
            w3 = target_px_to_world(p) - cam
            dst.append([w3[0] * fx / w3[2] + cx, w3[1] * fy / w3[2] + cy])
        warp = cv2.getPerspectiveTransform(src, np.float32(dst))
        img = cv2.warpPerspective(tgt, warp, (W, H), borderValue=180)

        z = (-(n @ cam + d) / (rays @ n)) * rays[..., 2]
        z = z + rng.normal(0.0, noise_mm / 1000.0, z.shape)

        name = 'frame_%06d' % fi
        cv2.imwrite(str(out_dir / 'images' / (name + '.jpg')),
                    cv2.cvtColor(img, cv2.COLOR_GRAY2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(out_dir / 'depth' / (name + '.png')),
                    np.clip(z * 1000, 0, 65535).astype(np.uint16))
        cams[name + '.jpg'] = cam
    return cams


def _write_colmap_poses(path, cams):
    """회전 없는 카메라들을 COLMAP images.txt로 적는다 (SfM 단위 = 미터)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# Image list', '# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME']
    for i, (name, c) in enumerate(sorted(cams.items()), 1):
        # world→camera 평행이동은 -C (회전이 단위행렬이므로)
        lines.append('%d 1 0 0 0 %.9f %.9f %.9f 1 %s' % (i, -c[0], -c[1], -c[2], name))
        lines.append('')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


@pytest.fixture(scope='module')
def scan(tmp_path_factory):
    root = tmp_path_factory.mktemp('scale')
    target = root / 'target.png'
    sys.argv = ['make_scale_target.py', '--out', str(target)]
    make_target_main()
    cams = _render_scan(root / 'frames', target)
    _write_colmap_poses(root / 'frames' / 'colmap' / 'sparse' / '0' / 'images.txt', cams)
    truth = json.loads((root / 'target.json').read_text(encoding='utf-8'))
    return root, truth


def test_target_is_detectable_at_working_distance(scan):
    """0.7m에서 마커가 읽혀야 한다 — 종이에서 크게 보이는 것과 다른 문제다."""
    root, truth = scan
    per_frame, _ = verify_scale.collect(str(root / 'frames'), truth)
    assert len(per_frame) >= N_FRAMES * 0.8, '대부분의 프레임에서 읽혀야 한다'
    seen = {i for markers in per_frame.values() for i in markers}
    assert seen == {0, 1, 2, 3}, '마커 네 개가 모두 보여야 한다'


def test_depth_accuracy_within_half_percent(scan):
    """검증 1: 한 프레임 안의 치수가 인쇄 치수와 맞아야 한다."""
    root, truth = scan
    per_frame, _ = verify_scale.collect(str(root / 'frames'), truth)
    rows = verify_scale.check_depth_accuracy(per_frame, truth)
    assert rows
    errs = [(m - t) / t * 100.0 for _, t, m in rows]
    # 코너를 depth에서 직접 읽으면 9mm 노이즈가 10%로 번진다. 평면맞춤 + 시선교차를
    # 쓰기 때문에 0.5% 안에 들어와야 한다 — 이 여유가 그 설계의 값어치다.
    assert abs(float(np.median(errs))) < 0.5, '중앙값 오차 %.2f%%' % np.median(errs)


@pytest.mark.parametrize('injected', [0.0, 0.05, -0.03])
def test_sfm_scale_error_is_recovered(scan, injected):
    """검증 2: 스케일을 일부러 틀리게 주면 그 값이 부호까지 나와야 한다."""
    root, truth = scan
    per_frame, _ = verify_scale.collect(str(root / 'frames'), truth)
    poses = verify_scale.read_colmap_images(
        str(root / 'frames' / 'colmap' / 'sparse' / '0' / 'images.txt'))
    result = verify_scale.check_sfm_scale(per_frame, poses, scale=1.0 + injected)
    assert result is not None
    slope = result[0]
    recovered = slope / (1.0 - slope)
    assert recovered == pytest.approx(injected, abs=0.005), \
        '주입 %+.1f%% → 복원 %+.2f%%' % (injected * 100, recovered * 100)


def test_depth_check_is_blind_to_sfm_scale(scan):
    """검증 1과 2는 독립이어야 한다 — 스케일이 틀려도 검증 1은 흔들리지 않는다."""
    root, truth = scan
    per_frame, _ = verify_scale.collect(str(root / 'frames'), truth)
    rows = verify_scale.check_depth_accuracy(per_frame, truth)
    # check_depth_accuracy는 포즈를 아예 받지 않는다. 구조로 보장되지만,
    # 나중에 누가 포즈를 끌어들이면 이 테스트가 막아준다.
    assert 'poses' not in verify_scale.check_depth_accuracy.__code__.co_varnames
    assert rows
