import json
import os
import statistics
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

# 같은 물리적 균열로 볼 map 좌표 반경. 스캔하며 지나가는 동안 같은 균열이
# 수십 프레임에 걸쳐 반복 탐지되는데, 프레임마다 bbox 중심이 조금씩 달라서
# map 좌표도 흔들린다. 이 반경 안이면 같은 균열의 반복 관측으로 묶는다.
# (D455F의 depth 노이즈가 1~1.5m 거리에서 2cm 수준인 걸 감안한 값)
DEFAULT_MERGE_RADIUS_M = 0.15


class CrackCollectorNode(Node):
    """반복 관측된 크랙 탐지를 map 좌표 기준으로 병합해 파일로 남기는 노드.

    `crack_fusion_node`가 프레임마다 발행하는 `/crack_fusion/tagged_detections`
    는 "이 순간 보이는 크랙들"이라 그대로 두면 스캔이 끝나는 순간 사라진다.
    이 노드는 그걸 누적해서 같은 위치의 관측들을 하나로 묶고, 스캔 결과물
    (크랙 목록 + 각각의 3D 위치/크기)을 JSON으로 저장한다.

    크기(mm)는 평균이 아니라 **중앙값**을 쓴다 — depth가 무효한 프레임에서
    나온 튀는 값이 섞여도 결과가 크게 흔들리지 않게 하기 위함
    (docs 8번 항목 1의 "관측 병합(A안)" 설계 그대로).
    """

    def __init__(self):
        super().__init__('crack_collector_node')

        self.declare_parameter('output_path', os.path.expanduser('~/.ros/cracks.json'))
        self.declare_parameter('merge_radius_m', DEFAULT_MERGE_RADIUS_M)
        self.declare_parameter('write_interval_s', 5.0)

        self._output_path = self.get_parameter('output_path').value
        self._merge_radius = float(self.get_parameter('merge_radius_m').value)

        self._clusters = []  # 각 원소: {'positions': [...], 'lengths': [...], ...}
        self._observation_count = 0

        self.create_subscription(
            String, '/crack_fusion/tagged_detections', self._on_tagged, 10
        )
        # 주기적으로도 써둔다 — 재생이 강제 종료돼도 그때까지의 결과는 남도록
        self.create_timer(float(self.get_parameter('write_interval_s').value), self._write)

        self.get_logger().info(
            f'crack_collector_node started (output={self._output_path}, '
            f'merge_radius={self._merge_radius}m)'
        )

    def _on_tagged(self, msg):
        try:
            detections = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        for det in detections:
            pos = det.get('map_position_m')
            if not pos or len(pos) != 3:
                continue
            self._observation_count += 1
            self._add_observation(det, pos)

    def _add_observation(self, det, pos):
        cluster = self._find_cluster(pos)
        if cluster is None:
            cluster = {'positions': [], 'lengths': [], 'widths': [], 'confidences': [], 'classes': {}}
            self._clusters.append(cluster)

        cluster['positions'].append(pos)
        if det.get('length_mm') is not None:
            cluster['lengths'].append(float(det['length_mm']))
        if det.get('width_mm') is not None:
            cluster['widths'].append(float(det['width_mm']))
        if det.get('confidence') is not None:
            cluster['confidences'].append(float(det['confidence']))
        cls = det.get('class', 'unknown')
        cluster['classes'][cls] = cluster['classes'].get(cls, 0) + 1

    def _find_cluster(self, pos):
        # 클러스터 수가 많아야 수십 개 수준이라 선형 탐색으로 충분하다
        r2 = self._merge_radius ** 2
        for cluster in self._clusters:
            cx, cy, cz = self._centroid(cluster['positions'])
            d2 = (cx - pos[0]) ** 2 + (cy - pos[1]) ** 2 + (cz - pos[2]) ** 2
            if d2 <= r2:
                return cluster
        return None

    @staticmethod
    def _centroid(positions):
        n = len(positions)
        return (
            sum(p[0] for p in positions) / n,
            sum(p[1] for p in positions) / n,
            sum(p[2] for p in positions) / n,
        )

    def _summarize(self):
        cracks = []
        for cluster in self._clusters:
            cx, cy, cz = self._centroid(cluster['positions'])
            cracks.append({
                'map_position_m': [round(cx, 4), round(cy, 4), round(cz, 4)],
                'observations': len(cluster['positions']),
                'class': max(cluster['classes'], key=cluster['classes'].get),
                'confidence_max': round(max(cluster['confidences']), 3) if cluster['confidences'] else None,
                'length_mm_median': round(statistics.median(cluster['lengths']), 1) if cluster['lengths'] else None,
                'width_mm_median': round(statistics.median(cluster['widths']), 1) if cluster['widths'] else None,
                # mm값이 몇 번이나 실제로 측정됐는지 — depth 무효로 측정 실패한
                # 관측이 많으면 이 값이 observations보다 훨씬 작게 나온다
                'length_samples': len(cluster['lengths']),
                'width_samples': len(cluster['widths']),
            })
        # 관측이 많은(= 여러 프레임에서 반복 확인된) 것부터 — 신뢰도 순 정렬
        cracks.sort(key=lambda c: c['observations'], reverse=True)
        return cracks

    def _write(self):
        cracks = self._summarize()
        payload = {
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'merge_radius_m': self._merge_radius,
            'total_observations': self._observation_count,
            'crack_count': len(cracks),
            'cracks': cracks,
        }
        tmp = self._output_path + '.tmp'
        os.makedirs(os.path.dirname(self._output_path) or '.', exist_ok=True)
        with open(tmp, 'w') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        # 쓰는 도중 종료돼도 이전 결과가 깨지지 않도록 원자적 교체
        os.replace(tmp, self._output_path)

    def destroy_node(self):
        self._write()
        self.get_logger().info(
            f'크랙 {len(self._clusters)}개 (관측 {self._observation_count}회) → {self._output_path}'
        )
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CrackCollectorNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # 재생 스크립트가 SIGINT로 파이프라인 전체를 정리하는 게 정상 종료
        # 경로라, 그때 나는 ExternalShutdownException을 예외 취급하지 않는다
        # (안 잡으면 트레이스백 + exit code 1로 종료돼 로그가 지저분해짐).
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
