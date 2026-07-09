import rclpy
from rclpy.node import Node


class DroneCoreNode(Node):
    """MAVROS 통신, FC 제어 및 비행 상태 모니터링을 담당하는 노드."""

    def __init__(self):
        super().__init__('drone_core_node')

        # TODO: MAVROS 토픽 구독/발행 예정
        # - 구독: /mavros/state, /mavros/local_position/pose 등
        # - 발행: /mavros/setpoint_position/local 등

        self.get_logger().info('drone_core_node started')


def main(args=None):
    rclpy.init(args=args)
    node = DroneCoreNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
