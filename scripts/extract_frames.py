#!/usr/bin/env python3
"""녹화해둔 bag에서 SfM에 쓸 컬러/depth 프레임을 짝지어 뽑아낸다 (A안 1단계).

젯슨에서 `ros2 bag play`와 함께 돌린다:
    ros2 run ... 대신 직접:
    python3 scripts/extract_frames.py --out ~/frames/wall &
    ros2 bag play ~/bags/wall_20260820_113158 --rate 2

**ExactTime 동기화를 쓰는 이유**: 2026-08-25에 이 bag의 헤더 스탬프를 전수 측정한
결과 99.0%(1,526/1,541)가 컬러/depth 완전히 같은 스탬프였고, 나머지 15장은 depth
짝이 아예 없는 고아 프레임이었다. ApproximateTime을 쓰면 그 15장이 66.7ms 떨어진
엉뚱한 depth와 짝지어져 재구성에 오차로 들어간다. ExactTime을 쓰면 그런 짝이
자동으로 버려진다 — 같은 세션에서 개선안으로 적어둔 걸 여기선 처음부터 적용.

**촬영 거리로 프레임을 걸러내는 이유**: depth 노이즈가 거리²에 비례한다는 것이
2026-09 실측으로 확인됐다(0.5m σ5.3mm / 0.65m σ9.2mm / 1.0m σ20.7mm,
모델 σ(mm) ≈ 20.9 × z²). 비행 중 거리를 완벽히 유지하기는 어렵지만, 어차피
오프라인으로 재구성하므로 **대역 밖 프레임을 여기서 버리면** 재촬영 없이 품질을
지킬 수 있다. `--min-dist`/`--max-dist`로 지정하며, 기본은 거르지 않고 거리만
기록한다(무엇이 찍혔는지 먼저 보고 판단하라는 뜻).

산출물:
    <out>/images/frame_000001.jpg   컬러 (COLMAP 입력)
    <out>/depth/frame_000001.png    16bit depth, 1단위=1mm
    <out>/intrinsics.json           fx, fy, cx, cy, depth_scale_m
    <out>/stamps.txt                프레임이름 <-> ROS 타임스탬프 <-> 촬영 거리(m)
"""

import argparse
import json
import os

import cv2
import numpy as np
import message_filters
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image


ROI_RATIO = 0.4   # 촬영 거리를 잴 화면 중앙 영역(가장자리는 다른 물체가 섞임)


def frame_distance_m(depth_img):
    """프레임의 촬영 거리(화면 중앙부 depth 중앙값, m). 잴 수 없으면 None."""
    h, w = depth_img.shape[:2]
    dy, dx = int(h * (1 - ROI_RATIO) / 2), int(w * (1 - ROI_RATIO) / 2)
    roi = depth_img[dy:h - dy, dx:w - dx]
    valid = roi[roi > 0]
    if valid.size < roi.size * 0.15:
        return None
    return float(np.median(valid)) * 0.001


class FrameExtractor(Node):
    def __init__(self, out_dir, every_n, jpeg_quality, min_dist, max_dist):
        super().__init__('frame_extractor')
        self.out_dir = out_dir
        self.every_n = every_n
        self.jpeg_quality = jpeg_quality
        self.min_dist = min_dist
        self.max_dist = max_dist
        self.distances = []
        self.skipped_dist = 0
        self.bridge = CvBridge()
        self.seen = 0
        self.saved = 0
        self.intrinsics_written = False

        os.makedirs(os.path.join(out_dir, 'images'), exist_ok=True)
        os.makedirs(os.path.join(out_dir, 'depth'), exist_ok=True)
        self.stamps = open(os.path.join(out_dir, 'stamps.txt'), 'w', encoding='utf-8')
        self.stamps.write('# frame_name ros_stamp_sec distance_m\n')

        color = message_filters.Subscriber(self, Image, '/camera/camera/color/image_raw')
        depth = message_filters.Subscriber(
            self, Image, '/camera/camera/aligned_depth_to_color/image_raw')
        info = message_filters.Subscriber(
            self, CameraInfo, '/camera/camera/color/camera_info')
        # ExactTime — 위 주석 참고. 스탬프가 정확히 같은 짝만 통과시킨다.
        sync = message_filters.TimeSynchronizer([color, depth, info], queue_size=200)
        sync.registerCallback(self.on_frame)

    def on_frame(self, color_msg, depth_msg, info_msg):
        self.seen += 1
        if (self.seen - 1) % self.every_n != 0:
            return

        if not self.intrinsics_written:
            k = info_msg.k
            with open(os.path.join(self.out_dir, 'intrinsics.json'), 'w', encoding='utf-8') as f:
                json.dump({'fx': k[0], 'fy': k[4], 'cx': k[2], 'cy': k[5],
                           'width': info_msg.width, 'height': info_msg.height,
                           'depth_scale_m': 0.001,
                           'note': 'aligned_depth_to_color 기준 — 컬러와 같은 내부파라미터'},
                          f, indent=2)
            self.intrinsics_written = True
            self.get_logger().info('intrinsics 저장: fx=%.2f fy=%.2f cx=%.2f cy=%.2f'
                                   % (k[0], k[4], k[2], k[5]))

        color = self.bridge.imgmsg_to_cv2(color_msg, desired_encoding='bgr8')
        depth = self.bridge.imgmsg_to_cv2(depth_msg, desired_encoding='passthrough')

        dist = frame_distance_m(depth)
        if dist is not None:
            self.distances.append(dist)
        if self.min_dist is not None or self.max_dist is not None:
            if dist is None \
                    or (self.min_dist is not None and dist < self.min_dist) \
                    or (self.max_dist is not None and dist > self.max_dist):
                self.skipped_dist += 1
                return

        self.saved += 1
        name = 'frame_%06d' % self.saved
        cv2.imwrite(os.path.join(self.out_dir, 'images', name + '.jpg'), color,
                    [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        cv2.imwrite(os.path.join(self.out_dir, 'depth', name + '.png'), depth)

        stamp = color_msg.header.stamp.sec + color_msg.header.stamp.nanosec * 1e-9
        self.stamps.write('%s.jpg %.9f %s\n'
                          % (name, stamp, '%.3f' % dist if dist is not None else 'nan'))
        self.stamps.flush()
        if self.saved % 50 == 0:
            self.get_logger().info('저장 %d장 (수신 %d)' % (self.saved, self.seen))

    def destroy_node(self):
        self.stamps.close()
        super().destroy_node()


def main():
    ap = argparse.ArgumentParser(description='bag에서 컬러/depth 프레임 쌍을 추출')
    ap.add_argument('--out', required=True, help='출력 디렉토리')
    ap.add_argument('--every-n', type=int, default=1,
                    help='N장에 1장만 저장(기본 1=전부). SfM은 겹침이 크면 느려지므로 '
                         '프레임이 많을 땐 2~3을 쓸 수 있다')
    ap.add_argument('--jpeg-quality', type=int, default=95,
                    help='JPEG 품질(기본 95) — 압축 아티팩트는 특징점 매칭을 해치므로 높게')
    ap.add_argument('--min-dist', type=float,
                    help='이보다 가까운 프레임은 버린다(m). 0.45 아래는 D455F depth 자체를 '
                         '믿을 수 없고, 0.6 아래는 최소 인식거리에 가까워 위험하다')
    ap.add_argument('--max-dist', type=float,
                    help='이보다 먼 프레임은 버린다(m). 노이즈가 거리²로 커진다 — '
                         '0.8m에서 σ13mm, 1.0m에서 σ21mm')
    args = ap.parse_args()

    rclpy.init()
    node = FrameExtractor(args.out, args.every_n, args.jpeg_quality,
                          args.min_dist, args.max_dist)
    node.get_logger().info('대기 중 — 이제 다른 터미널에서 ros2 bag play를 실행하세요')
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info('총 %d장 저장 (수신 %d쌍)' % (node.saved, node.seen))
        if node.skipped_dist:
            node.get_logger().info('거리 대역 밖이라 버린 프레임: %d장' % node.skipped_dist)
        if node.distances:
            d = np.array(node.distances)
            node.get_logger().info(
                '촬영 거리: 중앙값 %.2fm (10~90%% %.2f~%.2fm)'
                % (np.median(d), np.percentile(d, 10), np.percentile(d, 90)))
            for lo, hi, tag in ((0.0, 0.45, '너무 가까움'), (0.45, 0.60, '가까움'),
                                (0.60, 0.80, '적정'), (0.80, 1.20, '멂'),
                                (1.20, 99.0, '너무 멂')):
                n = int(((d >= lo) & (d < hi)).sum())
                if n:
                    node.get_logger().info('  %.2f~%.2fm %-8s %4d장 (%.0f%%)'
                                           % (lo, hi, tag, n, 100.0 * n / len(d)))
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
