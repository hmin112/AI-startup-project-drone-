import json
import threading

import rclpy
from rclpy.node import Node
from rtabmap_msgs.msg import Info
from std_msgs.msg import String


class LidarMappingNode(Node):
    """RTAB-Map(D455F 기반 Visual SLAM) 상태 요약/중계 노드.

    2026-08-07 하드웨어 최종화로 RPLIDAR가 빠지면서 이 노드는 더 이상
    /scan을 직접 다루지 않는다 — 실제 SLAM 연산(오도메트리+맵빌딩)은
    launch/bridge_drone.launch.py의 rgbd_odometry/rtabmap 노드가 전담하고,
    이 노드는 그 결과(/info, rtabmap_msgs/Info)를 구독해서 web_dashboard 등
    다른 소비자를 위한 단순 상태 요약(/lidar_mapping/status)만 발행한다 —
    예전 /scan 기반 status 발행 계약(connected + 통계)과 같은 자리.
    """

    def __init__(self):
        super().__init__('lidar_mapping_node')

        self._lock = threading.Lock()
        self._latest_info = None
        self._loop_closure_count = 0

        self.create_subscription(Info, '/info', self._on_info, 10)
        self._status_pub = self.create_publisher(String, '/lidar_mapping/status', 10)

        self.create_timer(1.0, self._publish_status)

        self.get_logger().info('lidar_mapping_node started')

    def _on_info(self, msg):
        with self._lock:
            self._latest_info = msg
            if msg.loop_closure_id > 0:
                self._loop_closure_count += 1

    def _publish_status(self):
        with self._lock:
            info = self._latest_info
            loop_closure_count = self._loop_closure_count

        if info is None:
            status = {'connected': False}
        else:
            status = {
                'connected': True,
                'map_node_count': info.ref_id,
                'last_loop_closure_id': info.loop_closure_id,
                'loop_closure_count': loop_closure_count,
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
