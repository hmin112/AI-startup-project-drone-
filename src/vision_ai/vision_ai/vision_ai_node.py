import json
import threading

import numpy as np
import pyrealsense2 as rs
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String
from sensor_msgs.msg import Image
from ultralytics import YOLO

from vision_ai import measurement

CAPTURE_WARMUP_FRAMES = 30


class VisionAiNode(Node):
    """RealSense D455F 연동 및 YOLO 기반 실시간 균열 탐지 + mm 크기 측정 노드."""

    def __init__(self):
        super().__init__('vision_ai_node')

        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('publish_rate_hz', 10.0)

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._latest_detections = []
        self._latest_annotated = None
        self._stop_event = threading.Event()

        self._detections_pub = self.create_publisher(String, '/vision_ai/detections', 10)
        self._annotated_pub = self.create_publisher(
            Image, '/vision_ai/annotated', qos_profile_sensor_data
        )

        publish_rate_hz = self.get_parameter('publish_rate_hz').value
        self.create_timer(1.0 / publish_rate_hz, self._publish_latest)

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        self.get_logger().info('vision_ai_node started')

    def _capture_loop(self):
        model_path = self.get_parameter('model_path').value
        model = YOLO(model_path)
        self.get_logger().info(f'YOLO model loaded: {model_path}, device={model.device}')

        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 30)
        config.enable_stream(rs.stream.color, 1280, 800, rs.format.bgr8, 30)
        pipeline.start(config)
        align = rs.align(rs.stream.color)

        try:
            for _ in range(CAPTURE_WARMUP_FRAMES):
                pipeline.wait_for_frames()

            while not self._stop_event.is_set():
                frames = pipeline.wait_for_frames()
                aligned_frames = align.process(frames)
                depth_frame = aligned_frames.get_depth_frame()
                color_frame = aligned_frames.get_color_frame()
                if not depth_frame or not color_frame:
                    continue

                color_image = np.asanyarray(color_frame.get_data())
                intrinsics = depth_frame.profile.as_video_stream_profile().get_intrinsics()
                height, width = color_image.shape[:2]

                results = model(color_image, device=0, verbose=False)
                result = results[0]
                detections = [
                    self._describe_detection(box, model.names, depth_frame, intrinsics, width, height)
                    for box in result.boxes
                ]
                annotated = result.plot()

                with self._lock:
                    self._latest_detections = detections
                    self._latest_annotated = annotated
        finally:
            pipeline.stop()

    def _describe_detection(self, box, class_names, depth_frame, intrinsics, width, height):
        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
        x1, x2 = sorted((max(0, min(x1, width - 1)), max(0, min(x2, width - 1))))
        y1, y2 = sorted((max(0, min(y1, height - 1)), max(0, min(y2, height - 1))))
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        return {
            'class': class_names[int(box.cls[0])],
            'confidence': float(box.conf[0]),
            'bbox': [x1, y1, x2, y2],
            'width_mm': self._safe_measure(depth_frame, intrinsics, (x1, cy), (x2, cy)),
            'height_mm': self._safe_measure(depth_frame, intrinsics, (cx, y1), (cx, y2)),
        }

    def _safe_measure(self, depth_frame, intrinsics, point_a, point_b):
        try:
            return measurement.measure_distance_mm(depth_frame, intrinsics, point_a, point_b)
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

    def destroy_node(self):
        self._stop_event.set()
        self._capture_thread.join(timeout=5.0)
        super().destroy_node()


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
