"""convert_deepcrack_to_yolo_seg.py의 mask_to_yolo_lines() 유닛 테스트.
실행: `pytest scripts/test/` (cv2/numpy만 필요, ROS 불필요).
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from convert_deepcrack_to_yolo_seg import MIN_CONTOUR_AREA, mask_to_yolo_lines  # noqa: E402


def _write_mask(path, mask_array):
    cv2.imwrite(str(path), mask_array)


def test_single_rectangle_produces_one_polygon(tmp_path):
    mask = np.zeros((100, 200), dtype=np.uint8)
    mask[20:40, 30:90] = 255  # 20x60 = 1200px^2, well above MIN_CONTOUR_AREA
    mask_path = tmp_path / "mask.png"
    _write_mask(mask_path, mask)

    lines = mask_to_yolo_lines(str(mask_path), img_width=200, img_height=100)

    assert len(lines) == 1
    parts = lines[0].split()
    assert parts[0] == "0"  # class id
    coords = [float(v) for v in parts[1:]]
    # 전부 [0, 1] 범위 안에 있어야 함(이미지 크기로 정규화됐는지 확인)
    assert all(0.0 <= c <= 1.0 for c in coords)


def test_empty_mask_produces_no_lines(tmp_path):
    mask = np.zeros((100, 200), dtype=np.uint8)
    mask_path = tmp_path / "empty.png"
    _write_mask(mask_path, mask)

    lines = mask_to_yolo_lines(str(mask_path), img_width=200, img_height=100)
    assert lines == []


def test_tiny_speckle_below_min_area_is_dropped(tmp_path):
    mask = np.zeros((100, 200), dtype=np.uint8)
    mask[10:12, 10:12] = 255  # 2x2 = 4px^2, well below MIN_CONTOUR_AREA(15)
    mask_path = tmp_path / "speckle.png"
    _write_mask(mask_path, mask)

    lines = mask_to_yolo_lines(str(mask_path), img_width=200, img_height=100)
    assert lines == []


def test_two_separate_regions_produce_two_polygons(tmp_path):
    mask = np.zeros((100, 200), dtype=np.uint8)
    mask[10:30, 10:30] = 255  # region 1
    mask[60:80, 150:190] = 255  # region 2, far apart -> separate contours
    mask_path = tmp_path / "two_regions.png"
    _write_mask(mask_path, mask)

    lines = mask_to_yolo_lines(str(mask_path), img_width=200, img_height=100)
    assert len(lines) == 2


def test_missing_file_returns_empty_list_not_crash(tmp_path):
    missing_path = tmp_path / "does_not_exist.png"
    lines = mask_to_yolo_lines(str(missing_path), img_width=200, img_height=100)
    assert lines == []


def test_min_contour_area_constant_is_positive():
    # 회귀 방지용 sanity check — 이 상수가 실수로 0/음수가 되면 노이즈
    # 필터링이 무력화됨.
    assert MIN_CONTOUR_AREA > 0
