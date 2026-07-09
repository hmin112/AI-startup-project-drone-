import rclpy
from rclpy.node import Node


class WebDashboardNode(Node):
    """분석 결과 및 3D 디지털 트윈 실시간 웹 시각화 노드."""

    def __init__(self):
        super().__init__('web_dashboard_node')

        # TODO: 각 노드 topic 구독 후 WebSocket으로 브라우저에 전달 예정
        # - drone_core, vision_ai, lidar_mapping 토픽 구독
        # - WebSocket 서버 기동 및 static/index.html 서빙

        self.get_logger().info('web_dashboard_node started')


def main(args=None):
    rclpy.init(args=args)
    node = WebDashboardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
