"""convert_uavpdd_to_yolo_seg.py의 xml_to_yolo_lines() 유닛 테스트.
실행: `pytest scripts/test/` (표준 라이브러리만 필요).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from convert_uavpdd_to_yolo_seg import CRACK_CLASSES, xml_to_yolo_lines  # noqa: E402

VOC_TEMPLATE = """<annotation>
  <folder/>
  <filename>{filename}</filename>
  <size>
    <height>{height}</height>
    <width>{width}</width>
    <depth>3</depth>
  </size>
  {objects}
</annotation>
"""

OBJECT_TEMPLATE = """<object>
    <name>{name}</name>
    <pose/>
    <truncated/>
    <difficult/>
    <bndbox>
      <xmin>{xmin}</xmin>
      <ymin>{ymin}</ymin>
      <xmax>{xmax}</xmax>
      <ymax>{ymax}</ymax>
    </bndbox>
  </object>"""


def _write_xml(path, objects, width=2592, height=1944):
    objects_xml = "\n  ".join(
        OBJECT_TEMPLATE.format(name=o["name"], xmin=o["xmin"], ymin=o["ymin"], xmax=o["xmax"], ymax=o["ymax"])
        for o in objects
    )
    path.write_text(VOC_TEMPLATE.format(filename="sample.jpg", height=height, width=width, objects=objects_xml))


def test_transverse_crack_extracted_as_rectangle(tmp_path):
    xml_path = tmp_path / "sample.xml"
    _write_xml(xml_path, [
        {"name": "Transverse crack", "xmin": 100, "ymin": 200, "xmax": 300, "ymax": 250},
    ], width=2592, height=1944)

    lines = xml_to_yolo_lines(str(xml_path), img_width=2592, img_height=1944)

    assert len(lines) == 1
    parts = lines[0].split()
    assert parts[0] == "0"
    coords = [float(v) for v in parts[1:]]
    assert len(coords) == 8  # 4 corners x (x, y)
    # 첫 코너는 (xmin, ymin) 정규화된 값
    assert abs(coords[0] - 100 / 2592) < 1e-6
    assert abs(coords[1] - 200 / 1944) < 1e-6


def test_all_four_crack_subtypes_kept(tmp_path):
    xml_path = tmp_path / "sample.xml"
    objects = [
        {"name": name, "xmin": 10, "ymin": 10, "xmax": 50, "ymax": 50}
        for name in ["Longitudinal crack", "Transverse crack", "Oblique crack", "Alligator crack"]
    ]
    _write_xml(xml_path, objects)

    lines = xml_to_yolo_lines(str(xml_path), img_width=2592, img_height=1944)
    assert len(lines) == 4


def test_non_crack_classes_dropped(tmp_path):
    # Pothole/Repair는 이 프로젝트 스코프 밖(단일 크랙 클래스 모델) — 제외돼야 함.
    xml_path = tmp_path / "sample.xml"
    _write_xml(xml_path, [
        {"name": "Pothole", "xmin": 10, "ymin": 10, "xmax": 50, "ymax": 50},
        {"name": "Repair", "xmin": 60, "ymin": 60, "xmax": 100, "ymax": 100},
    ])

    lines = xml_to_yolo_lines(str(xml_path), img_width=2592, img_height=1944)
    assert lines == []


def test_no_objects_returns_empty(tmp_path):
    xml_path = tmp_path / "sample.xml"
    _write_xml(xml_path, [])

    lines = xml_to_yolo_lines(str(xml_path), img_width=2592, img_height=1944)
    assert lines == []


def test_crack_classes_constant_matches_expected_four():
    # 회귀 방지 — 누군가 실수로 클래스 목록을 바꾸면 여기서 걸림.
    assert CRACK_CLASSES == {
        "Longitudinal crack", "Transverse crack", "Oblique crack", "Alligator crack",
    }
