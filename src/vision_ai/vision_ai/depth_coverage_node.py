import numpy as np
import rclpy
from cv_bridge import CvBridge
from message_filters import ApproximateTimeSynchronizer, Subscriber
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

# depth 무효(0) 픽셀을 반투명 빨간색으로 덮어 그려서, 카메라를 어느 방향으로
# 움직여야 depth가 잘 잡히는지(=SLAM 트래킹/mm 측정이 잘 될 방향인지)를
# 실시간으로 눈으로 보고 판단할 수 있게 하는 노드. vision_ai_node의 YOLO
# 추론과는 독립된 별도 노드(장애 격리 원칙, docs Core Rules 참고) — 무거운
# 연산이 없어서 구독 콜백에서 바로 계산해도 executor를 블록할 정도는 아님.
RED_BGR = np.array([0, 0, 255], dtype=np.float32)
OVERLAY_ALPHA = 0.55
PUBLISH_INTERVAL_S = 0.1  # 카메라 원본은 ~30Hz라 10Hz로 스로틀


class DepthCoverageNode(Node):
    def __init__(self):
        super().__init__('depth_coverage_node')
        self._bridge = CvBridge()
        self._last_publish_time = 0.0

        self._overlay_pub = self.create_publisher(
            Image, '/vision_ai/depth_coverage', qos_profile_sensor_data
        )

        color_sub = Subscriber(
            self, Image, '/camera/camera/color/image_raw', qos_profile=qos_profile_sensor_data
        )
        depth_sub = Subscriber(
            self,
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            qos_profile=qos_profile_sensor_data,
        )
        self._sync = ApproximateTimeSynchronizer([color_sub, depth_sub], queue_size=10, slop=0.05)
        self._sync.registerCallback(self._on_frames)

        self.get_logger().info('depth_coverage_node started')

    def _on_frames(self, color_msg, depth_msg):
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._last_publish_time < PUBLISH_INTERVAL_S:
            return
        self._last_publish_time = now

        color_image = self._bridge.imgmsg_to_cv2(color_msg, desired_encoding='bgr8')
        depth_image = self._bridge.imgmsg_to_cv2(depth_msg, desired_encoding='passthrough')

        invalid = depth_image == 0
        overlay = color_image.astype(np.float32)
        overlay[invalid] = overlay[invalid] * (1 - OVERLAY_ALPHA) + RED_BGR * OVERLAY_ALPHA
        overlay = overlay.astype(np.uint8)

        self._overlay_pub.publish(self._bridge.cv2_to_imgmsg(overlay, encoding='bgr8'))


def main(args=None):
    rclpy.init(args=args)
    node = DepthCoverageNode()
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
