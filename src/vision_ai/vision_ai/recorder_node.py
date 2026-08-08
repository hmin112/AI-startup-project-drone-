import os
import queue
import threading
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

# 인코딩이 카메라 속도를 못 따라갈 때 버퍼링할 최대 프레임 수(30fps 기준
# 약 2초치) — 이보다 밀리면 오래된 프레임부터 버림.
MAX_QUEUE_FRAMES = 60


class RecorderNode(Node):
    """D455F 원본 컬러 영상을 H.264로 압축해서 디스크에 저장하는 노드.

    착륙 후 정밀 3D 재구성용 원본 데이터를 보관하려는 목적(docs 5번 항목:
    "착륙 후엔 저장해둔 원본 데이터를 옮겨서 정밀 3D 맵 재구성"). 저장용량
    추정(docs 8번 항목 8)은 H.264 20Mbps를 가정했는데, `cv2.VideoWriter`
    (FFmpeg 백엔드, avc1 fourcc)는 비트레이트를 직접 지정하는 옵션이 없어서
    인코더 기본값을 그대로 씀 — 실제 파일 크기가 추정치와 얼마나 맞는지는
    아직 실측 안 됨.

    인코딩(카메라 속도 대비 무거울 수 있음)은 별도 스레드에서 처리 —
    구독 콜백 안에서 동기 인코딩하면 executor를 블록시키는 문제가
    생김(vision_ai_node에서 실측으로 확인된 패턴과 같은 이유로 미리 회피).
    """

    def __init__(self):
        super().__init__('recorder_node')

        self.declare_parameter(
            'output_dir', os.path.expanduser('~/bridge_drone_ws/recordings')
        )
        self.declare_parameter('fps', 30.0)

        self._output_dir = self.get_parameter('output_dir').value
        os.makedirs(self._output_dir, exist_ok=True)
        self._fps = self.get_parameter('fps').value

        self._bridge = CvBridge()
        self._frame_queue = queue.Queue(maxsize=MAX_QUEUE_FRAMES)
        self._stop_event = threading.Event()
        self._writer = None
        self._output_path = None

        self.create_subscription(
            Image, '/camera/camera/color/image_raw', self._on_color, qos_profile_sensor_data
        )

        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

        self.get_logger().info(f'recorder_node started, writing to {self._output_dir}')

    def _on_color(self, msg):
        frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        try:
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            # 완전성보다 실시간성 우선 — 이 프로젝트의 다른 큐/버퍼들과 같은
            # 원칙(오래된 프레임부터 버리고 최신을 우선).
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                pass

    def _writer_loop(self):
        while not self._stop_event.is_set():
            try:
                frame = self._frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if self._writer is None:
                height, width = frame.shape[:2]
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                self._output_path = os.path.join(self._output_dir, f'flight_{timestamp}.mp4')
                fourcc = cv2.VideoWriter_fourcc(*'avc1')
                self._writer = cv2.VideoWriter(self._output_path, fourcc, self._fps, (width, height))
                self.get_logger().info(f'recording to {self._output_path}')

            self._writer.write(frame)

    def destroy_node(self):
        self._stop_event.set()
        self._writer_thread.join(timeout=5.0)
        if self._writer is not None:
            self._writer.release()
            self.get_logger().info(f'recording saved: {self._output_path}')
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RecorderNode()
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
