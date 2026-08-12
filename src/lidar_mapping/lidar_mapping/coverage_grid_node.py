import json
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from tf2_ros import Buffer, LookupException, TransformListener

from lidar_mapping.coverage_math import build_status_payload, position_to_cell


class CoverageGridNode(Node):
    """검사 구간을 정사각형 격자로 나눠 스캔 완료 여부만 추적/발행하는 노드.

    문서(docs/bridge_drone_project_summary.md 5번 항목)의 설계를 코드로
    옮김: 원본 영상을 계속 보내는 대신, 드론의 현재 위치(`map` 프레임)를
    격자 칸으로 환산해서 "이 칸은 스캔했다"는 아주 작은 데이터만 주기적으로
    발행한다 — 저대역폭에서도 실시간 진행 확인이 가능하게 하려는 목적.

    칸 크기 기본값(1.5m)은 D455F가 1m 거리에서 커버하는 실제 면적 추정치
    (~1.9m x 1.1m, docs 8번 항목 6 참고)에서 절충한 값 — 실측 아님.

    카메라 자세(orientation)나 실측 거리는 반영하지 않고, 드론의 현재
    (x, y) 위치가 속한 칸 하나만 "스캔됨"으로 표시하는 단순화된 근사임
    (실제 카메라 FOV 풋프린트 전체를 투영하려면 자세+대상까지의 실측
    거리가 필요한데, 지금은 그 정밀도까지는 필요 없다고 판단).
    """

    SOURCE_FRAME = 'base_link'
    TARGET_FRAME = 'map'

    def __init__(self):
        super().__init__('coverage_grid_node')

        self.declare_parameter('cell_size_m', 1.5)
        self.declare_parameter('publish_rate_hz', 1.0)

        self._cell_size_m = self.get_parameter('cell_size_m').value

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._lock = threading.Lock()
        self._covered_cells = set()

        self._status_pub = self.create_publisher(String, '/coverage_grid/status', 10)

        publish_rate_hz = self.get_parameter('publish_rate_hz').value
        self.create_timer(1.0 / publish_rate_hz, self._tick)

        self.get_logger().info(f'coverage_grid_node started (cell_size={self._cell_size_m}m)')

    def _tick(self):
        try:
            transform = self._tf_buffer.lookup_transform(
                self.TARGET_FRAME, self.SOURCE_FRAME, rclpy.time.Time()
            )
        except LookupException:
            return
        except Exception as exc:
            self.get_logger().warn(f'TF lookup failed: {exc}', throttle_duration_sec=5.0)
            return

        x = transform.transform.translation.x
        y = transform.transform.translation.y
        cell = position_to_cell(x, y, self._cell_size_m)

        with self._lock:
            self._covered_cells.add(cell)
            covered_cells = set(self._covered_cells)

        status = build_status_payload(covered_cells, self._cell_size_m)
        self._status_pub.publish(String(data=json.dumps(status)))


def main(args=None):
    rclpy.init(args=args)
    node = CoverageGridNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
