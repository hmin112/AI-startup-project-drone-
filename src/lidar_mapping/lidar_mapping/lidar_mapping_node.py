import rclpy
from rclpy.node import Node


class LidarMappingNode(Node):
    """LiDAR SLAM, 센서 퓨전, 3D 포인트클라우드 맵 생성 노드."""

    def __init__(self):
        super().__init__('lidar_mapping_node')

        # TODO: SLAM 처리, Open3D 연동 예정
        # - LiDAR 스캔/포인트클라우드 구독
        # - SLAM 기반 위치 추정 및 맵 생성
        # - Open3D를 이용한 3D 포인트클라우드 후처리

        self.get_logger().info('lidar_mapping_node started')


def main(args=None):
    rclpy.init(args=args)
    node = LidarMappingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
