import json
import os
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from message_filters import ApproximateTimeSynchronizer, Subscriber
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

# 촬영 중에 "이 스캔이 쓸만한가"를 조종자에게 알려주는 노드.
#
# 왜 필요한가: 지금은 찍고 내려와서 추출·SfM·융합을 30분 돌려야 결과를 안다. 거기서
# 망친 걸 알면 다시 날아야 한다. 스캔을 망치는 원인은 전부 촬영 중에 감지 가능한데,
# 셋 다 "찍을 땐 멀쩡해 보이는데 나중에 SfM이 깨지는" 종류라 현장에서 알 방법이 없었다:
#   · 거리 이탈    — 2026-09-14 스캔의 25%가 목표 대역 밖이었다
#   · 모션 블러    — 빠른 공전에서 스케일 추정이 ±7.5%로 흔들려 정합 오차 16mm를 냈다
#   · 텍스처 부족  — 콘크리트 교량 하부의 핵심 위험(docs 8번 항목 3)
#
# **연산을 의도적으로 가볍게 유지한다.** 촬영-후처리 분리 워크플로(2026-08-20)는 촬영
# 중 CPU를 비워두려고 만든 것이고, 실시간 SLAM이 프레임을 대량으로 버려 지도가 조각난
# 게 그 이유였다. 그 전제를 깨지 않으려고 모든 지표를 축소 영상에서 낮은 주기로 계산하며,
# YOLO 같은 무거운 추론은 여기서 절대 돌리지 않는다(균열은 나중에 찾으면 된다).
#
# 대역폭도 가볍게: ELRS가 2.4GHz로 바뀌어 WiFi와 대역을 공유하므로(docs 8번 항목 7)
# 영상으로 WiFi를 채우면 조종 링크와 싸운다. 이 노드는 작은 JSON만 보낸다.

ROI_RATIO = 0.4             # 화면 중앙 40%만 본다(가장자리는 다른 물체가 섞임)
WORK_WIDTH = 320            # 지표 계산용 축소 폭 — 비용을 여기서 결정한다
PUBLISH_INTERVAL_S = 0.25   # 4Hz. 사람이 보고 반응하기 충분하고 부하도 작다

# 거리 대역. 2026-09 실측으로 depth 노이즈가 거리²에 비례함이 확인됐다
# (σ(mm) ≈ 20.9 × z²: 0.50m 5.3mm / 0.65m 9.15mm / 1.0m 20.7mm). 여기에
# "결함이 약 15~20픽셀보다 커야 depth 형상에 남는다"를 겹치면 0.6~0.8m가 목표.
NEAR_M = 0.60
FAR_M = 0.80
TOO_CLOSE_M = 0.45          # 이 아래는 D455F depth 자체를 믿을 수 없다

MIN_DEPTH_COVERAGE = 0.15   # 유효 depth가 이보다 적으면 거리를 말하지 않는다
MIN_FEATURES = 150          # 이보다 적으면 SfM/오도메트리가 위태롭다
BLUR_DROP_RATIO = 0.40      # 최근 최선 대비 이 비율 밑이면 흔들린 것으로 본다


class CaptureMonitorNode(Node):
    def __init__(self):
        super().__init__('capture_monitor_node')
        self._bridge = CvBridge()
        self._last_publish = 0.0

        self.declare_parameter('near_m', NEAR_M)
        self.declare_parameter('far_m', FAR_M)
        self.declare_parameter('bag_dir', '')
        self._near = float(self.get_parameter('near_m').value)
        self._far = float(self.get_parameter('far_m').value)
        self._bag_dir = str(self.get_parameter('bag_dir').value)

        # 선명도는 장면마다 절대값이 크게 달라서 고정 임계값이 의미가 없다.
        # 최근에 본 가장 선명한 값을 기준으로 삼아 상대적으로 판정한다.
        self._sharp_best = 0.0
        self._frames = 0
        self._first_frame_t = None
        self._bag_size = 0
        self._bag_size_t = 0.0
        self._bag_growing = None

        self._pub = self.create_publisher(String, '/vision_ai/capture_quality', 10)
        color_sub = Subscriber(
            self, Image, '/camera/camera/color/image_raw', qos_profile=qos_profile_sensor_data
        )
        depth_sub = Subscriber(
            self, Image, '/camera/camera/aligned_depth_to_color/image_raw',
            qos_profile=qos_profile_sensor_data,
        )
        self._sync = ApproximateTimeSynchronizer(
            [color_sub, depth_sub], queue_size=5, slop=0.05
        )
        self._sync.registerCallback(self._on_frames)
        self.get_logger().info(
            'capture_monitor_node started — 목표 거리 %.2f~%.2f m%s'
            % (self._near, self._far, (', bag=%s' % self._bag_dir) if self._bag_dir else '')
        )

    # --- 지표들 ---------------------------------------------------------------

    def _distance(self, depth):
        h, w = depth.shape[:2]
        dy, dx = int(h * (1 - ROI_RATIO) / 2), int(w * (1 - ROI_RATIO) / 2)
        roi = depth[dy:h - dy, dx:w - dx]
        valid = roi[roi > 0]
        coverage = float(valid.size) / max(1, roi.size)
        if coverage < MIN_DEPTH_COVERAGE:
            return None, coverage
        # 중앙값 — 앞을 스쳐가는 물체나 depth 튐에 끌려가지 않게
        return float(np.median(valid)) * 0.001, coverage

    def _sharpness_and_features(self, gray):
        # 라플라시안 분산: 초점/움직임 흐림에 민감한 고전적 지표.
        sharp = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        # 특징점 수: SfM과 RTAB-Map이 모두 GFTT 계열을 쓰므로 같은 걸로 센다
        # (config/rtabmap_tuning.yaml의 Vis/FeatureType=8). 실제로 추적에 쓰이는
        # 인라이어는 이보다 훨씬 적으므로 여유 있게 세어야 한다.
        corners = cv2.goodFeaturesToTrack(
            gray, maxCorners=600, qualityLevel=0.01, minDistance=7
        )
        return sharp, 0 if corners is None else len(corners)

    def _recording(self):
        """bag 디렉토리가 실제로 커지고 있는지. 촬영 실패를 즉시 알기 위한 것."""
        if not self._bag_dir or not os.path.isdir(self._bag_dir):
            return None, None
        now = time.time()
        if now - self._bag_size_t < 2.0:
            return self._bag_size, self._bag_growing
        total = 0
        for root, _dirs, files in os.walk(self._bag_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        if self._bag_size_t:
            self._bag_growing = total > self._bag_size
        self._bag_size, self._bag_size_t = total, now
        return total, self._bag_growing

    # --- 콜백 -----------------------------------------------------------------

    def _on_frames(self, color_msg, depth_msg):
        self._frames += 1
        now = self.get_clock().now().nanoseconds / 1e9
        if self._first_frame_t is None:
            self._first_frame_t = now
        if now - self._last_publish < PUBLISH_INTERVAL_S:
            return
        self._last_publish = now

        depth = self._bridge.imgmsg_to_cv2(depth_msg, desired_encoding='passthrough')
        distance_m, coverage = self._distance(depth)

        color = self._bridge.imgmsg_to_cv2(color_msg, desired_encoding='bgr8')
        h, w = color.shape[:2]
        scale = WORK_WIDTH / float(w)
        small = cv2.resize(color, (WORK_WIDTH, max(1, int(h * scale))),
                           interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        sharp, features = self._sharpness_and_features(gray)

        # 최근 최선을 천천히 잊게 해서 장면이 바뀌어도 기준이 따라가게 한다
        self._sharp_best = max(sharp, self._sharp_best * 0.99)
        sharp_ratio = sharp / self._sharp_best if self._sharp_best > 1e-6 else 1.0

        fps = (self._frames / (now - self._first_frame_t)) if now > self._first_frame_t else 0.0
        bag_bytes, bag_growing = self._recording()

        if distance_m is None:
            dist_state = 'unknown'
        elif distance_m < TOO_CLOSE_M:
            dist_state = 'too_close'
        elif distance_m < self._near:
            dist_state = 'close'
        elif distance_m > self._far:
            dist_state = 'far'
        else:
            dist_state = 'ok'

        blur_state = 'blurred' if sharp_ratio < BLUR_DROP_RATIO else 'ok'
        texture_state = 'weak' if features < MIN_FEATURES else 'ok'
        if bag_growing is None:
            rec_state = 'unknown'
        else:
            rec_state = 'ok' if bag_growing else 'stalled'

        # 가장 나쁜 항목이 전체 상태 — 조종자는 이것만 봐도 된다
        worst = 'ok'
        for st in (dist_state, blur_state, texture_state, rec_state):
            if st in ('too_close', 'stalled'):
                worst = 'bad'
            elif st in ('close', 'far', 'blurred', 'weak') and worst == 'ok':
                worst = 'warn'

        msg = String()
        msg.data = json.dumps({
            'capture_quality': True,
            'overall': worst,
            'standoff_m': round(distance_m, 3) if distance_m is not None else None,
            'depth_coverage': round(coverage, 3),
            'state': dist_state,
            'target_m': [self._near, self._far],
            'sharpness': round(sharp, 1),
            'sharpness_ratio': round(sharp_ratio, 3),
            'blur_state': blur_state,
            'features': int(features),
            'texture_state': texture_state,
            'fps': round(fps, 1),
            'bag_bytes': bag_bytes,
            'rec_state': rec_state,
        })
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = CaptureMonitorNode()
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
