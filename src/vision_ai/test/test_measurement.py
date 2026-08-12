"""measurement.py 유닛 테스트 — pyrealsense2가 필요해서 젯슨에서 실행
(`pytest src/vision_ai/test/`, `source /opt/ros/humble/setup.bash` 후).
이 Mac(Apple Silicon)엔 pyrealsense2 pip 배포가 없어서 로컬 실행 불가 —
2026-08-12 확인.

핀홀 카메라 모델 공식(실측 원값: 2026-07-13 우드락 실험, 1.4m 거리에서
59.1mm 측정/실제 55mm, 오차 7.5%)을 합성 케이스로 재검증. 이전 세션들에
서 즉석 스크립트로 여러 번 확인했던 걸 재사용 가능한 정식 테스트로 정리.
"""
import sys
from pathlib import Path

import numpy as np
import pyrealsense2 as rs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision_ai.measurement import deproject_point_m, measure_distance_mm  # noqa: E402


def _synthetic_intrinsics(width=1280, height=800, fx=650.0, fy=650.0, ppx=640.0, ppy=400.0):
    intr = rs.intrinsics()
    intr.width = width
    intr.height = height
    intr.fx = fx
    intr.fy = fy
    intr.ppx = ppx
    intr.ppy = ppy
    intr.model = rs.distortion.none
    intr.coeffs = [0.0, 0.0, 0.0, 0.0, 0.0]
    return intr


def test_measure_distance_mm_flat_plane_known_pixel_gap():
    # 평면(같은 깊이 1.0m)에서 fx=650인 카메라 기준, 65px 간격은
    # (65/650)*1.0*1000 = 100mm — 핀홀 공식으로 정확히 검증 가능한 케이스.
    depth_image = np.full((800, 1280), 1000, dtype=np.uint16)  # 1000 unit * 0.001 = 1.0m
    intr = _synthetic_intrinsics()

    distance_mm = measure_distance_mm(depth_image, 0.001, intr, (600, 400), (665, 400))
    assert abs(distance_mm - 100.0) < 0.5


def test_measure_distance_mm_raises_on_zero_depth():
    depth_image = np.zeros((800, 1280), dtype=np.uint16)
    intr = _synthetic_intrinsics()

    try:
        measure_distance_mm(depth_image, 0.001, intr, (600, 400), (665, 400))
        assert False, "expected ValueError for zero depth"
    except ValueError:
        pass


def test_measure_distance_mm_raises_if_only_one_point_invalid():
    depth_image = np.full((800, 1280), 1000, dtype=np.uint16)
    depth_image[400, 600] = 0  # point_a만 무효
    intr = _synthetic_intrinsics()

    try:
        measure_distance_mm(depth_image, 0.001, intr, (600, 400), (665, 400))
        assert False, "expected ValueError when either point has zero depth"
    except ValueError:
        pass


def test_deproject_point_m_center_pixel_at_principal_point():
    # 주점(ppx, ppy)과 정확히 일치하는 픽셀은 광축 위에 있으므로
    # x=y=0, z=depth가 나와야 함.
    depth_image = np.full((800, 1280), 1000, dtype=np.uint16)
    intr = _synthetic_intrinsics(ppx=640.0, ppy=400.0)

    point_3d = deproject_point_m(depth_image, 0.001, intr, (640, 400))
    assert abs(point_3d[0]) < 1e-6
    assert abs(point_3d[1]) < 1e-6
    assert abs(point_3d[2] - 1.0) < 1e-6


def test_deproject_point_m_returns_none_on_zero_depth():
    depth_image = np.zeros((800, 1280), dtype=np.uint16)
    intr = _synthetic_intrinsics()

    assert deproject_point_m(depth_image, 0.001, intr, (640, 400)) is None


def test_measure_distance_mm_matches_woodock_field_measurement_order_of_magnitude():
    # 2026-07-13 실측: 1.4m 거리에서 55mm 흠집이 평균 59.1mm로 측정됨
    # (오차 7.5%, 30프레임 평균). 여기선 정확한 재현이 아니라, 같은
    # 자릿수/범위의 합성 케이스가 핀홀 공식과 일치하는지만 재확인 —
    # 실측 자체는 이미 하드웨어로 검증된 것이고, 이 테스트는 리팩터링
    # 과정에서 그 수학이 깨지지 않았는지 보는 회귀 방지용.
    depth_image = np.full((800, 1280), 1400, dtype=np.uint16)  # 1.4m
    intr = _synthetic_intrinsics(fx=650.0)
    # 55mm에 해당하는 픽셀 간격 역산: px = 55mm/1000 / 1.4m * fx = 0.0393*650 ≈ 25.5px
    px_gap = round(0.055 / 1.4 * 650.0)

    distance_mm = measure_distance_mm(depth_image, 0.001, intr, (600, 400), (600 + px_gap, 400))
    assert abs(distance_mm - 55.0) < 2.0  # 픽셀 반올림 오차 감안
