"""커버리지 그리드의 순수 계산 로직 — rclpy 의존성 없이 유닛 테스트하기
위해 `coverage_grid_node.py`에서 분리(`vision_ai/measurement.py`와 같은
패턴: 노드 파일은 ROS I/O만, 실제 계산은 별도 순수 모듈로).
"""
import math


def position_to_cell(x, y, cell_size_m):
    """world 좌표(x, y)가 속하는 격자 칸의 (칸_x, 칸_y) 인덱스를 반환."""
    return (math.floor(x / cell_size_m), math.floor(y / cell_size_m))


def build_status_payload(covered_cells, cell_size_m):
    """누적된 칸 집합으로 `/coverage_grid/status`에 실릴 딕셔너리를 구성."""
    cells = list(covered_cells)
    return {
        'cell_size_m': cell_size_m,
        'covered_cell_count': len(cells),
        'estimated_area_m2': round(len(cells) * cell_size_m ** 2, 1),
        'covered_cells': cells,
    }
