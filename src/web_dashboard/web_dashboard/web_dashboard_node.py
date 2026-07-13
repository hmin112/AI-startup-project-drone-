import asyncio
import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import cv2
import rclpy
import websockets
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

JPEG_QUALITY = 80


class WebDashboardNode(Node):
    """분석 결과 및 3D 디지털 트윈 실시간 웹 시각화 노드."""

    def __init__(self):
        super().__init__('web_dashboard_node')

        self.declare_parameter('http_port', 8080)
        self.declare_parameter('ws_port', 8765)

        self._clients = set()
        self._loop = None
        self._loop_ready = threading.Event()
        self._bridge = CvBridge()

        self._ws_thread = threading.Thread(target=self._run_ws_server, daemon=True)
        self._ws_thread.start()
        self._loop_ready.wait(timeout=5.0)

        self._http_server = self._start_http_server()

        self.create_subscription(String, '/vision_ai/detections', self._on_detections, 10)
        self.create_subscription(
            Image, '/vision_ai/annotated', self._on_annotated, qos_profile_sensor_data
        )

        http_port = self.get_parameter('http_port').value
        ws_port = self.get_parameter('ws_port').value
        self.get_logger().info(f'web_dashboard_node started (http=:{http_port}, ws=:{ws_port})')

    def _run_ws_server(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        ws_port = self.get_parameter('ws_port').value

        async def handler(websocket):
            self._clients.add(websocket)
            try:
                async for _ in websocket:
                    pass  # 브라우저 -> 서버 메시지는 아직 사용하지 않음
            finally:
                self._clients.discard(websocket)

        async def serve():
            async with websockets.serve(handler, '0.0.0.0', ws_port):
                self._loop_ready.set()
                await asyncio.Future()  # run forever

        self._loop.run_until_complete(serve())

    def _start_http_server(self):
        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        handler = functools.partial(SimpleHTTPRequestHandler, directory=static_dir)
        http_port = self.get_parameter('http_port').value
        server = ThreadingHTTPServer(('0.0.0.0', http_port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def _on_detections(self, msg):
        if not self._clients or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(msg.data), self._loop)

    def _on_annotated(self, msg):
        if not self._clients or self._loop is None:
            return
        frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(buf.tobytes()), self._loop)

    async def _broadcast(self, payload):
        dead = set()
        for client in list(self._clients):
            try:
                await client.send(payload)
            except websockets.ConnectionClosed:
                dead.add(client)
        self._clients -= dead

    def destroy_node(self):
        self._http_server.shutdown()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = WebDashboardNode()
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
