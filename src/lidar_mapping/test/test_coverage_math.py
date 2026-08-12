"""coverage_math.py 유닛 테스트 — rclpy 불필요, `pytest src/lidar_mapping/test/`로 실행."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lidar_mapping.coverage_math import build_status_payload, position_to_cell  # noqa: E402


def test_position_to_cell_origin():
    assert position_to_cell(0.0, 0.0, 1.5) == (0, 0)


def test_position_to_cell_positive():
    # 1.5m 칸에서 x=2.0m는 칸 인덱스 1 (1.5 <= 2.0 < 3.0)
    assert position_to_cell(2.0, 3.4, 1.5) == (1, 2)


def test_position_to_cell_negative():
    # 음수 좌표는 floor 방향 주의 — -0.1m는 칸 -1 (0이 아님)
    assert position_to_cell(-0.1, -1.6, 1.5) == (-1, -2)


def test_position_to_cell_exact_boundary():
    # 정확히 칸 경계(1.5의 배수)는 다음 칸의 시작점
    assert position_to_cell(1.5, 3.0, 1.5) == (1, 2)


def test_position_to_cell_matches_real_flight_test():
    # 2026-08-08 세션에서 젯슨에 합성 TF로 실측 검증했던 값 그대로 재현
    # (x=2.0, y=3.0, cell_size=1.5 -> (1, 2)).
    assert position_to_cell(2.0, 3.0, 1.5) == (1, 2)


def test_build_status_payload_empty():
    payload = build_status_payload(set(), 1.5)
    assert payload == {
        'cell_size_m': 1.5,
        'covered_cell_count': 0,
        'estimated_area_m2': 0.0,
        'covered_cells': [],
    }


def test_build_status_payload_area_calculation():
    cells = {(0, 0), (1, 0), (0, 1)}
    payload = build_status_payload(cells, 1.5)
    assert payload['covered_cell_count'] == 3
    # build_status_payload는 소수 1자리로 반올림(round)한다 — 3*1.5^2=6.75 -> 6.8.
    assert math.isclose(payload['estimated_area_m2'], round(3 * 1.5 ** 2, 1), rel_tol=1e-9)
    assert sorted(payload['covered_cells']) == sorted(cells)
