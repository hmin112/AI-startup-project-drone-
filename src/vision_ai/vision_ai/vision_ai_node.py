import json
import threading

import cv2
import numpy as np
import pyrealsense2 as rs
import rclpy
from cv_bridge import CvBridge
from message_filters import ApproximateTimeSynchronizer, Subscriber
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from ultralytics import YOLO

from vision_ai import measurement

# D455F: 1 raw depth unit = 1mm (depth_scale_m_per_unit in
# models/camera_calibration/d455f_intrinsics_1280x720.json).
DEPTH_SCALE_M_PER_UNIT = 0.001


class VisionAiNode(Node):
    """D455F 컬러/depth 토픽 구독 + YOLO 기반 실시간 균열 탐지 + mm 크기 측정 노드.

    카메라 캡처는 realsense2_camera_node가 전담(단일 캡처 지점, launch 파일
    참고) — 이 노드는 그 노드가 발행하는 컬러/정렬된 depth 토픽을 구독만
    한다. D455F가 하나뿐이라 SLAM 파이프라인과 동시에 디바이스를 직접 여는
    것을 피하기 위한 구조.
    """

    def __init__(self):
        super().__init__('vision_ai_node')

        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('publish_rate_hz', 10.0)

        model_path = self.get_parameter('model_path').value
        self._model = YOLO(model_path)
        self.get_logger().info(f'YOLO model loaded: {model_path}, device={self._model.device}')

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._latest_detections = []
        self._latest_annotated = None
        self._intrinsics = None

        self._detections_pub = self.create_publisher(String, '/vision_ai/detections', 10)
        self._annotated_pub = self.create_publisher(
            Image, '/vision_ai/annotated', qos_profile_sensor_data
        )

        # 정렬된 depth의 camera_info를 써야 함(색상 해상도 기준 픽셀 좌표와
        # intrinsics가 일치) — 색상 camera_info를 쓰면 두 스트림 해상도가
        # 다를 때(예: depth 1280x720, color 1280x800) 어긋난다.
        self.create_subscription(
            CameraInfo,
            '/camera/camera/aligned_depth_to_color/camera_info',
            self._on_camera_info,
            qos_profile_sensor_data,
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

        publish_rate_hz = self.get_parameter('publish_rate_hz').value
        self.create_timer(1.0 / publish_rate_hz, self._publish_latest)

        self.get_logger().info('vision_ai_node started')

    def _on_camera_info(self, msg):
        if self._intrinsics is not None:
            return
        intr = rs.intrinsics()
        intr.width = msg.width
        intr.height = msg.height
        intr.fx = msg.k[0]
        intr.fy = msg.k[4]
        intr.ppx = msg.k[2]
        intr.ppy = msg.k[5]
        # 정렬된 depth 이미지는 이미 보정(rectify)된 상태로 발행되므로
        # 추가 왜곡 모델 없이 순수 핀홀 모델로 역투영하면 된다.
        intr.model = rs.distortion.none
        intr.coeffs = [0.0, 0.0, 0.0, 0.0, 0.0]
        self._intrinsics = intr
        self.get_logger().info('camera intrinsics received')

    def _on_frames(self, color_msg, depth_msg):
        if self._intrinsics is None:
            return

        color_image = self._bridge.imgmsg_to_cv2(color_msg, desired_encoding='bgr8')
        depth_image = self._bridge.imgmsg_to_cv2(depth_msg, desired_encoding='passthrough')
        height, width = color_image.shape[:2]

        results = self._model(color_image, device=0, verbose=False)
        result = results[0]
        masks_xy = result.masks.xy if result.masks is not None else [None] * len(result.boxes)
        detections = [
            self._describe_detection(box, mask_xy, self._model.names, depth_image, width, height)
            for box, mask_xy in zip(result.boxes, masks_xy)
        ]
        annotated = result.plot()

        with self._lock:
            self._latest_detections = detections
            self._latest_annotated = annotated

    def _describe_detection(self, box, mask_xy, class_names, depth_image, width, height):
        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
        x1, x2 = sorted((max(0, min(x1, width - 1)), max(0, min(x2, width - 1))))
        y1, y2 = sorted((max(0, min(y1, height - 1)), max(0, min(y2, height - 1))))

        if mask_xy is not None and len(mask_xy) >= 3:
            length_mm, width_mm = self._measure_from_mask(mask_xy, depth_image, width, height)
        else:
            length_mm, width_mm = self._measure_from_bbox(depth_image, x1, y1, x2, y2)

        # bbox 중심의 카메라 광학 프레임 3D 좌표(미터) — 2D→3D 맵 태깅용
        # (crack_fusion_node.py가 이 값을 map 좌표로 변환). 크기(mm)와
        # 별개로, "이 크랙이 어디 있는지" 위치 정보가 필요해서 추가.
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        center_camera_m = measurement.deproject_point_m(
            depth_image, DEPTH_SCALE_M_PER_UNIT, self._intrinsics, (cx, cy)
        )

        return {
            'class': class_names[int(box.cls[0])],
            'confidence': float(box.conf[0]),
            'bbox': [x1, y1, x2, y2],
            'length_mm': length_mm,
            'width_mm': width_mm,
            'center_camera_m': list(center_camera_m) if center_camera_m is not None else None,
        }

    def _measure_from_mask(self, mask_xy, depth_image, width, height):
        # Cracks are long, thin, and diagonal, so an axis-aligned bbox
        # over/under-estimates their true length/width. A rotated rect
        # fitted to the mask's own contour follows the crack's orientation.
        rect = cv2.minAreaRect(mask_xy.astype(np.float32))
        corners = [
            (int(np.clip(px, 0, width - 1)), int(np.clip(py, 0, height - 1)))
            for px, py in cv2.boxPoints(rect)
        ]
        edge_a = self._safe_measure(depth_image, corners[0], corners[1])
        edge_b = self._safe_measure(depth_image, corners[1], corners[2])
        return self._longer_shorter(edge_a, edge_b)

    def _measure_from_bbox(self, depth_image, x1, y1, x2, y2):
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        edge_a = self._safe_measure(depth_image, (x1, cy), (x2, cy))
        edge_b = self._safe_measure(depth_image, (cx, y1), (cx, y2))
        return self._longer_shorter(edge_a, edge_b)

    @staticmethod
    def _longer_shorter(edge_a, edge_b):
        edges = [e for e in (edge_a, edge_b) if e is not None]
        if not edges:
            return None, None
        if len(edges) == 1:
            return edges[0], None
        return max(edges), min(edges)

    def _safe_measure(self, depth_image, point_a, point_b):
        try:
            return measurement.measure_distance_mm(
                depth_image, DEPTH_SCALE_M_PER_UNIT, self._intrinsics, point_a, point_b
            )
        except ValueError:
            return None

    def _publish_latest(self):
        with self._lock:
            detections = self._latest_detections
            annotated = self._latest_annotated

        if annotated is None:
            return

        self._detections_pub.publish(String(data=json.dumps(detections)))
        self._annotated_pub.publish(self._bridge.cv2_to_imgmsg(annotated, encoding='bgr8'))


def main(args=None):
    rclpy.init(args=args)
    node = VisionAiNode()
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
