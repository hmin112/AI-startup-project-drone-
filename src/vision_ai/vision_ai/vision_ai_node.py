import rclpy
from rclpy.node import Node


class VisionAiNode(Node):
    """RealSense D455F 연동 및 YOLO 기반 실시간 균열 탐지 추론 노드."""

    def __init__(self):
        super().__init__('vision_ai_node')

        # TODO: YOLO 모델 로드, TensorRT 추론, 비동기 처리 예정
        # - RealSense D455F 컬러/뎁스 스트림 구독
        # - YOLO 모델 로드 및 TensorRT 엔진 변환
        # - 추론 결과(균열 위치/신뢰도) 토픽 발행

        self.get_logger().info('vision_ai_node started')


def main(args=None):
    rclpy.init(args=args)
    node = VisionAiNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
