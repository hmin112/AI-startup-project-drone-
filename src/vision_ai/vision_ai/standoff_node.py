import json

import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

# 촬영 대상과의 거리를 실시간으로 알려주는 노드.
#
# 왜 필요한가(2026-09-14~16 실측으로 확정된 근거):
#   depth 노이즈가 거리²에 정확히 비례한다. 세 번의 스캔이 하나의 모델로 설명됨 —
#       0.50m → σ 5.3mm,  0.65m → σ 9.15mm,  ~1.0m → σ 20.7mm
#       모델 σ(mm) ≈ 20.9 × z²  (z 단위 m)
#   여기에 "결함이 약 15~20픽셀보다 커야 depth 형상에 남는다"(2026-09-14, 848×480에서
#   20mm 결함이 스테레오 매칭 윈도우에 먹혀 사라진 실측)를 겹치면 거리에 따라
#   판별 가능한 최소 결함 크기가 정해진다:
#       0.6m → 약 14~19mm,  0.7m → 약 16~22mm,  1.0m → 약 23~31mm
#   아래로는 D455F 최소 인식거리(0.4m)와 2026-07-13에 겪은 "50cm 부근에서 depth가
#   실제의 2배로 측정" 문제가 막는다.
#
#   → 목표 대역 0.6~0.8m. 이 안에 들면 노이즈가 최선 대비 1.5배를 넘지 않는다.
#
# 조종자는 FPV 고글을 보고 있어서 이 값을 직접 볼 수 없다(FPV는 젯슨을 안 거치는
# 별도 경로 — docs 2번 항목 참고). 그래서 지상국에서 옆 사람이 보고 불러주는 용도로
# 만든다. 자동 거리 유지는 젯슨↔FC 통신이 뚫려야 가능하고 그건 FC 펌웨어 결정에
# 달려 있다(docs 8번 항목 3).
NEAR_M = 0.60
FAR_M = 0.80
TOO_CLOSE_M = 0.45          # 이 아래는 depth 자체를 믿을 수 없다
ROI_RATIO = 0.4             # 화면 중앙 40% 영역만 본다(가장자리는 다른 물체가 섞임)
PUBLISH_INTERVAL_S = 0.2    # 5Hz — 사람이 보고 반응하기 충분하고 부하도 작다


class StandoffNode(Node):
    def __init__(self):
        super().__init__('standoff_node')
        self._bridge = CvBridge()
        self._last_publish = 0.0

        self.declare_parameter('near_m', NEAR_M)
        self.declare_parameter('far_m', FAR_M)
        self._near = float(self.get_parameter('near_m').value)
        self._far = float(self.get_parameter('far_m').value)

        self._pub = self.create_publisher(String, '/vision_ai/standoff', 10)
        self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self._on_depth,
            qos_profile_sensor_data,
        )
        self.get_logger().info(
            'standoff_node started — 목표 대역 %.2f~%.2f m' % (self._near, self._far)
        )

    def _on_depth(self, msg):
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._last_publish < PUBLISH_INTERVAL_S:
            return
        self._last_publish = now

        depth = self._bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
        h, w = depth.shape[:2]
        dy, dx = int(h * (1 - ROI_RATIO) / 2), int(w * (1 - ROI_RATIO) / 2)
        roi = depth[dy:h - dy, dx:w - dx]
        valid = roi[roi > 0]

        # 유효 픽셀이 너무 적으면 거리를 말할 수 없다(검은 구멍, 반사면, 범위 밖).
        # 억지로 숫자를 내는 것보다 "모름"이 조종자에게 정직하다.
        coverage = float(valid.size) / max(1, roi.size)
        if coverage < 0.15:
            self._publish(None, coverage, 'unknown')
            return

        # 중앙값 — 앞을 스쳐가는 물체나 depth 튐에 끌려가지 않게
        distance_m = float(np.median(valid)) * 0.001
        if distance_m < TOO_CLOSE_M:
            state = 'too_close'
        elif distance_m < self._near:
            state = 'close'
        elif distance_m > self._far:
            state = 'far'
        else:
            state = 'ok'
        self._publish(distance_m, coverage, state)

    def _publish(self, distance_m, coverage, state):
        msg = String()
        msg.data = json.dumps({
            'standoff_m': round(distance_m, 3) if distance_m is not None else None,
            'depth_coverage': round(coverage, 3),
            'state': state,
            'target_m': [self._near, self._far],
        })
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = StandoffNode()
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
