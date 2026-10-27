#!/usr/bin/env python3
"""녹화해둔 bag을 ROS 없이 직접 읽어 컬러/depth 프레임 쌍을 뽑아낸다.

`extract_frames.py`와 **산출물이 완전히 같다**. 다른 건 단 하나, 젯슨이 필요 없다는
것이다. 기존 경로는 `ros2 bag play`가 토픽을 쏘고 ROS 노드가 받아 적는 구조라
젯슨(또는 ROS가 깔린 리눅스)에서만 돌았는데, 그 뒤 단계인 COLMAP·융합·탐지·뷰어는
전부 맥에서 돌고 있었다. 추출 한 단계 때문에 매번 젯슨을 켜고 파일을 내려받아야
했고, **2026-09·10에 microSD가 두 번 죽으면서 그 한 단계가 파이프라인 전체를
멈춰 세웠다.** bag 파일만 손에 있으면 처리가 끝까지 가야 한다.

bag은 특별한 포맷이 아니다 — SQLite 파일 하나에 토픽 표와 메시지 표가 있고,
메시지 본문은 zstd로 압축된 CDR(DDS 직렬화) 바이트다. 세 겹을 벗기면 끝이다.
그래서 이 스크립트는 `sqlite3`(표준 라이브러리) + `zstandard` + `numpy/cv2`만 쓴다.

**ExactTime 동기화는 그대로 유지한다.** 2026-08-25 전수 측정에서 99.0%가 컬러/depth
같은 스탬프였고 나머지는 짝이 없는 고아 프레임이었다. 여기서도 헤더 스탬프가 정확히
같은 쌍만 통과시키므로, 두 경로가 같은 프레임 집합을 뽑는다.

**헤더만 먼저 읽는 이유**: 1280×720 bag을 통째로 풀면 압축 해제본이 2GB에 달한다.
zstd는 스트리밍 해제가 되므로 1단계에서는 각 메시지의 **앞 256바이트만** 풀어
타임스탬프를 읽고, 2단계에서 짝이 맞은 메시지만 끝까지 푼다. 메모리는 한 프레임치면
충분하고, 버릴 프레임은 픽셀을 만들지도 않는다.

쓰는 법:
    python3 scripts/read_bag.py ~/bags/desk_scan_1 --out ~/frames/desk1
    python3 scripts/read_bag.py ~/bags/desk_scan_1 --list
"""

import argparse
import json
import os
import sqlite3
import struct
import sys

import cv2
import numpy as np

try:
    import zstandard
except ImportError:
    sys.exit('zstandard 모듈이 필요합니다:  pip3 install --user zstandard')


ROI_RATIO = 0.4   # 촬영 거리를 잴 화면 중앙 영역(가장자리는 다른 물체가 섞임)

COLOR_TOPIC = '/camera/camera/color/image_raw'
DEPTH_TOPIC = '/camera/camera/aligned_depth_to_color/image_raw'
INFO_TOPIC = '/camera/camera/color/camera_info'

HEADER_PEEK = 256   # 스탬프 + frame_id를 읽기에 넉넉한 길이


class Cdr:
    """CDR(Common Data Representation) 리더.

    ROS 2가 메시지를 바이트로 바꿀 때 쓰는 형식이다. 앞 4바이트는 캡슐화 헤더로
    바이트 순서를 알려주고, 그 뒤부터가 본문이다. **정렬 기준이 본문 시작점**이라
    오프셋을 본문 기준으로 세야 한다 — 여기서 4바이트를 빼먹으면 모든 필드가
    밀려서 터무니없는 값이 나온다.
    """

    def __init__(self, buf):
        if len(buf) < 4:
            raise ValueError('CDR 메시지가 너무 짧다 (%d바이트)' % len(buf))
        # buf[0:2] = 캡슐화 종류, buf[1]이 1이면 리틀엔디언
        self.little = buf[1] in (1, 3)
        self.body = buf[4:]
        self.pos = 0

    def _align(self, size):
        pad = (-self.pos) % size
        self.pos += pad

    def _unpack(self, fmt, size):
        self._align(size)
        value = struct.unpack_from(('<' if self.little else '>') + fmt,
                                   self.body, self.pos)[0]
        self.pos += size
        return value

    def u8(self):
        return self._unpack('B', 1)

    def i32(self):
        return self._unpack('i', 4)

    def u32(self):
        return self._unpack('I', 4)

    def f64(self):
        return self._unpack('d', 8)

    def string(self):
        n = self.u32()                      # 길이에 끝의 널 문자가 포함된다
        s = self.body[self.pos:self.pos + n - 1]
        self.pos += n
        return s.decode('utf-8', 'replace')

    def f64_array(self, n):
        self._align(8)
        a = np.frombuffer(self.body, dtype='<f8' if self.little else '>f8',
                          count=n, offset=self.pos)
        self.pos += 8 * n
        return a.tolist()

    def f64_sequence(self):
        return self.f64_array(self.u32())

    def u8_sequence(self):
        n = self.u32()
        b = self.body[self.pos:self.pos + n]
        self.pos += n
        return b

    def header(self):
        """std_msgs/Header — (스탬프 초, frame_id)."""
        sec = self.i32()
        nanosec = self.u32()
        return sec + nanosec * 1e-9, self.string()


def decode_image(buf):
    """sensor_msgs/msg/Image → (stamp, numpy 배열). 인코딩은 BGR/16bit로 맞춰 돌려준다."""
    c = Cdr(buf)
    stamp, _ = c.header()
    height, width = c.u32(), c.u32()
    encoding = c.string()
    c.u8()                      # is_bigendian — RealSense는 항상 0
    c.u32()                     # step — 아래에서 encoding으로 다시 계산한다
    data = c.u8_sequence()

    if encoding in ('rgb8', 'bgr8'):
        img = np.frombuffer(data, np.uint8).reshape(height, width, 3)
        # cv2는 BGR로 저장한다. rgb8이면 여기서 뒤집어야 색이 맞는다
        return stamp, img[:, :, ::-1] if encoding == 'rgb8' else img
    if encoding in ('16UC1', 'mono16'):
        return stamp, np.frombuffer(data, '<u2').reshape(height, width)
    if encoding == 'mono8':
        return stamp, np.frombuffer(data, np.uint8).reshape(height, width)
    raise ValueError('처리할 줄 모르는 이미지 인코딩: %s' % encoding)


def decode_camera_info(buf):
    """sensor_msgs/msg/CameraInfo → 내부 파라미터 dict."""
    c = Cdr(buf)
    c.header()
    height, width = c.u32(), c.u32()
    c.string()                  # distortion_model
    c.f64_sequence()            # d
    k = c.f64_array(9)
    return {'fx': k[0], 'fy': k[4], 'cx': k[2], 'cy': k[5],
            'width': width, 'height': height}


def peek_stamp(buf):
    """앞부분만 받아 헤더 스탬프를 읽는다 (본문 전체가 없어도 된다)."""
    return Cdr(buf).header()[0]


def frame_distance_m(depth_img):
    """프레임의 촬영 거리(화면 중앙부 depth 중앙값, m). 잴 수 없으면 None."""
    h, w = depth_img.shape[:2]
    dy, dx = int(h * (1 - ROI_RATIO) / 2), int(w * (1 - ROI_RATIO) / 2)
    roi = depth_img[dy:h - dy, dx:w - dx]
    valid = roi[roi > 0]
    if valid.size < roi.size * 0.15:
        return None
    return float(np.median(valid)) * 0.001


class Bag:
    """rosbag2 sqlite3 저장본 하나를 읽는다 (zstd MESSAGE 압축 지원)."""

    def __init__(self, path):
        if os.path.isdir(path):
            db3 = sorted(f for f in os.listdir(path) if f.endswith('.db3'))
            if not db3:
                raise SystemExit('%s 안에 .db3 파일이 없습니다' % path)
            if len(db3) > 1:
                raise SystemExit('.db3가 여러 개입니다 — 하나를 직접 지정하세요: %s'
                                 % ', '.join(db3))
            path = os.path.join(path, db3[0])
        self.path = path
        self.db = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        self.topics = {name: (tid, ttype) for tid, name, ttype
                       in self.db.execute('SELECT id, name, type FROM topics')}
        # 압축 여부는 metadata.yaml이 아니라 실제 바이트로 판단한다. 메타데이터가
        # 없거나 다른 디렉토리에 있는 bag도 그대로 읽히는 편이 낫다.
        self._dctx = zstandard.ZstdDecompressor()
        first = self.db.execute('SELECT data FROM messages LIMIT 1').fetchone()
        self.compressed = bool(first) and bytes(first[0][:4]) == b'\x28\xb5\x2f\xfd'

    def counts(self):
        rows = self.db.execute(
            'SELECT topic_id, COUNT(*) FROM messages GROUP BY topic_id')
        by_id = dict(rows)
        return {name: by_id.get(tid, 0) for name, (tid, _) in self.topics.items()}

    def _full(self, blob):
        return self._dctx.decompress(blob) if self.compressed else bytes(blob)

    def _head(self, blob, n=HEADER_PEEK):
        """앞 n바이트만 푼다 — 전체를 풀지 않으려는 것이 요점이다."""
        if not self.compressed:
            return bytes(blob[:n])
        with self._dctx.stream_reader(bytes(blob)) as r:
            return r.read(n)

    def stamps(self, topic):
        """[(rowid, 헤더 스탬프)] — 본문은 풀지 않는다."""
        tid = self.topics[topic][0]
        out = []
        for rowid, blob in self.db.execute(
                'SELECT rowid, data FROM messages WHERE topic_id=? ORDER BY timestamp',
                (tid,)):
            out.append((rowid, peek_stamp(self._head(blob))))
        return out

    def message(self, rowid):
        blob = self.db.execute('SELECT data FROM messages WHERE rowid=?',
                               (rowid,)).fetchone()[0]
        return self._full(blob)

    def first_message(self, topic):
        tid = self.topics[topic][0]
        row = self.db.execute(
            'SELECT data FROM messages WHERE topic_id=? ORDER BY timestamp LIMIT 1',
            (tid,)).fetchone()
        return self._full(row[0]) if row else None


def report_distances(distances, log):
    if not distances:
        return
    d = np.array(distances)
    log('촬영 거리: 중앙값 %.2fm (10~90%% %.2f~%.2fm)'
        % (np.median(d), np.percentile(d, 10), np.percentile(d, 90)))
    for lo, hi, tag in ((0.0, 0.45, '너무 가까움'), (0.45, 0.60, '가까움'),
                        (0.60, 0.80, '적정'), (0.80, 1.20, '멂'),
                        (1.20, 99.0, '너무 멂')):
        n = int(((d >= lo) & (d < hi)).sum())
        if n:
            log('  %.2f~%.2fm %-8s %4d장 (%.0f%%)' % (lo, hi, tag, n, 100.0 * n / len(d)))


def main():
    ap = argparse.ArgumentParser(
        description='bag을 ROS 없이 직접 읽어 컬러/depth 프레임 쌍을 추출')
    ap.add_argument('bag', help='bag 디렉토리 또는 .db3 파일')
    ap.add_argument('--out', help='출력 디렉토리')
    ap.add_argument('--list', action='store_true', help='토픽 목록만 보고 끝낸다')
    ap.add_argument('--every-n', type=int, default=1,
                    help='N장에 1장만 저장(기본 1=전부)')
    ap.add_argument('--jpeg-quality', type=int, default=95,
                    help='JPEG 품질(기본 95) — 압축 아티팩트는 특징점 매칭을 해친다')
    ap.add_argument('--min-dist', type=float,
                    help='이보다 가까운 프레임은 버린다(m)')
    ap.add_argument('--max-dist', type=float,
                    help='이보다 먼 프레임은 버린다(m). 노이즈가 거리²로 커진다')
    ap.add_argument('--color-topic', default=COLOR_TOPIC)
    ap.add_argument('--depth-topic', default=DEPTH_TOPIC)
    ap.add_argument('--info-topic', default=INFO_TOPIC)
    args = ap.parse_args()

    bag = Bag(args.bag)
    print('bag: %s (%s)' % (bag.path, 'zstd 압축' if bag.compressed else '비압축'))

    if args.list:
        counts = bag.counts()
        for name, (_, ttype) in sorted(bag.topics.items()):
            print('  %-50s %-32s %5d개' % (name, ttype, counts[name]))
        return

    if not args.out:
        ap.error('--out 또는 --list 중 하나가 필요합니다')

    for topic in (args.color_topic, args.depth_topic, args.info_topic):
        if topic not in bag.topics:
            raise SystemExit('bag에 %s 토픽이 없습니다 (--list로 확인하세요)' % topic)

    os.makedirs(os.path.join(args.out, 'images'), exist_ok=True)
    os.makedirs(os.path.join(args.out, 'depth'), exist_ok=True)

    intr = decode_camera_info(bag.first_message(args.info_topic))
    intr['depth_scale_m'] = 0.001
    intr['note'] = 'aligned_depth_to_color 기준 — 컬러와 같은 내부파라미터'
    with open(os.path.join(args.out, 'intrinsics.json'), 'w', encoding='utf-8') as f:
        json.dump(intr, f, indent=2)
    print('intrinsics 저장: fx=%.2f fy=%.2f cx=%.2f cy=%.2f'
          % (intr['fx'], intr['fy'], intr['cx'], intr['cy']))

    # 1단계 — 헤더만 읽어 짝을 맞춘다 (ExactTime: 스탬프가 정확히 같은 것만)
    color_stamps = bag.stamps(args.color_topic)
    depth_by_stamp = {}
    for rowid, stamp in bag.stamps(args.depth_topic):
        depth_by_stamp.setdefault(round(stamp, 9), rowid)
    pairs = [(c_row, depth_by_stamp[key], stamp)
             for c_row, stamp in color_stamps
             for key in (round(stamp, 9),) if key in depth_by_stamp]
    orphans = len(color_stamps) - len(pairs)
    print('컬러 %d장 중 %d쌍 동기화 (depth 짝 없는 고아 %d장은 버림)'
          % (len(color_stamps), len(pairs), orphans))

    # 2단계 — 짝이 맞은 것만 끝까지 풀어 저장한다
    stamps_path = os.path.join(args.out, 'stamps.txt')
    distances, skipped_dist, saved = [], 0, 0
    with open(stamps_path, 'w', encoding='utf-8') as out:
        out.write('# frame_name ros_stamp_sec distance_m\n')
        for i, (c_row, d_row, stamp) in enumerate(pairs):
            if i % args.every_n != 0:
                continue

            _, depth = decode_image(bag.message(d_row))
            dist = frame_distance_m(depth)
            if dist is not None:
                distances.append(dist)
            if args.min_dist is not None or args.max_dist is not None:
                if dist is None \
                        or (args.min_dist is not None and dist < args.min_dist) \
                        or (args.max_dist is not None and dist > args.max_dist):
                    skipped_dist += 1
                    continue

            _, color = decode_image(bag.message(c_row))
            saved += 1
            name = 'frame_%06d' % saved
            cv2.imwrite(os.path.join(args.out, 'images', name + '.jpg'), color,
                        [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            cv2.imwrite(os.path.join(args.out, 'depth', name + '.png'), depth)
            out.write('%s.jpg %.9f %s\n'
                      % (name, stamp, '%.3f' % dist if dist is not None else 'nan'))
            if saved % 50 == 0:
                print('저장 %d장' % saved)

    print('총 %d장 저장 → %s' % (saved, args.out))
    if skipped_dist:
        print('거리 대역 밖이라 버린 프레임: %d장' % skipped_dist)
    report_distances(distances, print)


if __name__ == '__main__':
    main()
