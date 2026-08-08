import json

import rclpy
import tf2_geometry_msgs  # noqa: F401 (registers PointStamped conversion for tf2_ros.Buffer.transform)
from geometry_msgs.msg import PointStamped
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from tf2_ros import Buffer, LookupException, TransformListener


class CrackFusionNode(Node):
    """`vision_ai`의 2D 크랙 탐지를 3D 지도(`map` 프레임) 좌표로 태깅하는 노드.

    프로젝트 문서 8번 항목 2("2D→3D 태깅") 참고. `vision_ai_node`가 이미
    각 탐지의 카메라 광학 프레임 3D 위치(`center_camera_m`)를 계산해서
    발행하므로, 여기서는 그 점을 tf2로 `map` 프레임까지 변환만 한다 —
    실제 좌표 계산(픽셀→카메라 3D)은 vision_ai/measurement.py에 이미
    있음, 여기서 재구현하지 않음.

    변환 체인: camera_color_optical_frame -> (realsense2_camera 자체 발행)
    -> camera_link -> (base_to_camera_tf, launch에서 static) -> base_link
    -> (rgbd_odometry) -> odom -> (rtabmap) -> map. 체인 중 하나라도 아직
    없으면(예: 카메라가 정지 상태라 rgbd_odometry가 "lost"라 odom 자체가
    없는 경우) 해당 탐지는 조용히 건너뛴다 — 크래시하지 않음.

    타이밍: `/vision_ai/detections`(std_msgs/String)엔 헤더/타임스탬프가
    없어서, 탐지 시점과 정확히 동기화된 TF 대신 "최신 사용 가능한" TF를
    사용한다(point.header.stamp를 비워서 tf2에 latest를 요청). 드론
    속도 대비 탐지 주기(~10Hz)가 충분히 빠르다고 가정한 근사 — 요구
    정밀도가 높아지면 vision_ai가 탐지 JSON에 타임스탬프를 싣도록
    바꾸고 여기서도 정확히 그 시점의 TF를 조회하도록 개선 필요.

    **실행기 주의**: `_to_map_frame()`이 `buffer.transform(..., timeout=...)`
    으로 최대 0.2초 블로킹 대기하는데, 이 노드가 싱글스레드 executor로
    돌면 그 대기 중엔 TF 리스너 자신의 구독 콜백도 같은 스레드를 못 얻어서
    못 돈다 — 즉 기다리는 동안 정작 기다리는 TF 메시지가 절대 도착 못
    하는 자기 자신을 막는 구조가 됨(실측 확인). `main()`에서 반드시
    `MultiThreadedExecutor`로 spin해야 이 대기가 의미 있게 동작한다.
    """

    SOURCE_FRAME = 'camera_color_optical_frame'
    TARGET_FRAME = 'map'

    def __init__(self):
        super().__init__('crack_fusion_node')

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self.create_subscription(String, '/vision_ai/detections', self._on_detections, 10)
        self._tagged_pub = self.create_publisher(String, '/crack_fusion/tagged_detections', 10)

        self.get_logger().info('crack_fusion_node started')

    def _on_detections(self, msg):
        try:
            detections = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        tagged = []
        for det in detections:
            center = det.get('center_camera_m')
            if center is None:
                continue

            map_position_m = self._to_map_frame(center)
            if map_position_m is None:
                continue

            tagged.append({**det, 'map_position_m': map_position_m})

        if tagged:
            self._tagged_pub.publish(String(data=json.dumps(tagged)))

    def _to_map_frame(self, center_camera_m):
        point = PointStamped()
        point.header.frame_id = self.SOURCE_FRAME
        point.header.stamp = Time().to_msg()  # 최신 사용 가능한 TF 요청
        point.point.x, point.point.y, point.point.z = center_camera_m

        try:
            transformed = self._tf_buffer.transform(
                point, self.TARGET_FRAME, timeout=Duration(seconds=0.2)
            )
        except LookupException:
            return None
        except Exception as exc:
            self.get_logger().warn(f'TF transform to map failed: {exc}', throttle_duration_sec=5.0)
            return None

        return [transformed.point.x, transformed.point.y, transformed.point.z]


def main(args=None):
    rclpy.init(args=args)
    node = CrackFusionNode()
    # 싱글스레드 executor면 TF 대기(_to_map_frame)가 그 TF를 배달할
    # 리스너 콜백과 스레드를 다퉈서 절대 성공 못 함 — 클래스 docstring
    # 참고. 반드시 멀티스레드로 돌려야 한다.
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
