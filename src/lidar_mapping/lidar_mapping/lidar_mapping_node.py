import json
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String


class LidarMappingNode(Node):
    """LiDAR SLAM, 센서 퓨전, 3D 포인트클라우드 맵 생성 노드."""

    def __init__(self):
        super().__init__('lidar_mapping_node')

        self._lock = threading.Lock()
        self._latest_scan = None

        # 실제 SLAM(위치 추정 + occupancy grid/3D 맵 생성)은 slam_toolbox
        # launch 구성으로 붙일 예정 (RPLIDAR A3 미보유로 아직 미착수). 이
        # 노드는 우선 원시 스캔을 구독해 기본 상태만 집계/발행한다.
        self.create_subscription(LaserScan, '/scan', self._on_scan, qos_profile_sensor_data)
        self._status_pub = self.create_publisher(String, '/lidar_mapping/status', 10)

        self.create_timer(1.0, self._publish_status)

        self.get_logger().info('lidar_mapping_node started')

    def _on_scan(self, msg):
        with self._lock:
            self._latest_scan = msg

    def _publish_status(self):
        with self._lock:
            scan = self._latest_scan

        if scan is None:
            status = {'connected': False}
        else:
            valid_ranges = [r for r in scan.ranges if scan.range_min <= r <= scan.range_max]
            status = {
                'connected': True,
                'num_points': len(scan.ranges),
                'num_valid_points': len(valid_ranges),
                'min_range_m': min(valid_ranges) if valid_ranges else None,
                'max_range_m': max(valid_ranges) if valid_ranges else None,
            }
        self._status_pub.publish(String(data=json.dumps(status)))


def main(args=None):
    rclpy.init(args=args)
    node = LidarMappingNode()
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
