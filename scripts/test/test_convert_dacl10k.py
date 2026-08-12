"""convert_dacl10k_to_yolo_seg.py의 annotation_to_yolo_lines() 유닛 테스트.
실행: `pytest scripts/test/` (표준 라이브러리만 필요).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from convert_dacl10k_to_yolo_seg import annotation_to_yolo_lines  # noqa: E402


def _write_annotation(path, shapes, image_name="sample.jpg", width=1600, height=1200):
    ann = {
        "shapes": shapes,
        "imagePath": image_name,
        "imageHeight": height,
        "imageWidth": width,
        "imageName": image_name,
        "split": "train",
        "dacl10k_version": "test",
    }
    path.write_text(json.dumps(ann))


def test_crack_shape_extracted(tmp_path):
    ann_path = tmp_path / "sample.json"
    _write_annotation(ann_path, [
        {"label": "Crack", "shape_type": "polygon", "points": [[100.0, 200.0], [110.0, 210.0], [90.0, 220.0]]},
    ])

    lines, image_name = annotation_to_yolo_lines(str(ann_path))

    assert image_name == "sample.jpg"
    assert len(lines) == 1
    parts = lines[0].split()
    assert parts[0] == "0"
    coords = [float(v) for v in parts[1:]]
    # 100/1600, 200/1200 정규화 확인 (첫 점)
    assert abs(coords[0] - 100.0 / 1600) < 1e-6
    assert abs(coords[1] - 200.0 / 1200) < 1e-6


def test_non_crack_classes_are_dropped(tmp_path):
    # dacl10k은 19개 클래스 멀티라벨 — Crack이 아닌 다른 손상 유형(Rust,
    # ACrack 등)은 이 프로젝트가 단일 클래스(crack)만 쓰므로 제외돼야 함.
    ann_path = tmp_path / "sample.json"
    _write_annotation(ann_path, [
        {"label": "Rust", "shape_type": "polygon", "points": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]},
        {"label": "ACrack", "shape_type": "polygon", "points": [[5.0, 5.0], [15.0, 5.0], [15.0, 15.0]]},
    ])

    lines, _ = annotation_to_yolo_lines(str(ann_path))
    assert lines == []


def test_degenerate_polygon_under_three_points_dropped(tmp_path):
    ann_path = tmp_path / "sample.json"
    _write_annotation(ann_path, [
        {"label": "Crack", "shape_type": "line", "points": [[0.0, 0.0], [10.0, 10.0]]},
    ])

    lines, _ = annotation_to_yolo_lines(str(ann_path))
    assert lines == []


def test_mixed_crack_and_other_classes_only_keeps_crack(tmp_path):
    ann_path = tmp_path / "sample.json"
    _write_annotation(ann_path, [
        {"label": "Crack", "shape_type": "polygon", "points": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]},
        {"label": "Spalling", "shape_type": "polygon", "points": [[20.0, 20.0], [30.0, 20.0], [30.0, 30.0]]},
        {"label": "Crack", "shape_type": "polygon", "points": [[40.0, 40.0], [50.0, 40.0], [50.0, 50.0]]},
    ])

    lines, _ = annotation_to_yolo_lines(str(ann_path))
    assert len(lines) == 2
    assert all(line.startswith("0 ") for line in lines)


def test_no_shapes_returns_empty(tmp_path):
    ann_path = tmp_path / "sample.json"
    _write_annotation(ann_path, [])

    lines, image_name = annotation_to_yolo_lines(str(ann_path))
    assert lines == []
    assert image_name == "sample.jpg"
