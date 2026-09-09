#!/usr/bin/env python3
"""카메라 포즈 + depth 이미지로 포인트클라우드를 만든다 (A안의 핵심).

목적: "8/20에 실측한 고스팅 σ 20.7mm는 depth 센서 노이즈가 아니라 포즈(궤적)
오차가 지배적"이라는 가설을 검증하는 것. 같은 depth 이미지를 **포즈만 바꿔서**
쌓아보면 포즈 개선분이 그대로 드러난다.

그래서 융합 방식은 일부러 가장 단순하게 — depth 픽셀을 3D로 역투영해서 포즈로
옮겨 쌓기만 한다(TSDF 같은 평균화 없음). 두 가지 이유:
  1. 8/20 기준선(`rtabmap-export`가 낸 포인트클라우드, σ 20.7mm)과 산출물
     형태가 같아야 직접 비교가 된다.
  2. TSDF는 여러 프레임 depth를 평균해 노이즈를 줄이는데, 그러면 포즈 개선
     효과와 평균화 효과가 섞여서 무엇 덕분에 좋아졌는지 알 수 없다.

비교 설계(3자):
    기준선  RTAB-Map 포즈 + rtabmap-export      → 8/20 실측 σ 20.7mm
    대조군  RTAB-Map 포즈 + 이 스크립트         → 이 스크립트가 기준선을 재현하는지 확인
    실험군  COLMAP(SfM) 포즈 + 이 스크립트      → 대조군과의 차이 = 순수 포즈 개선분

사용 예:
    ./fuse_depth.py --poses sparse/0/images.txt --pose-format colmap \\
        --depth-dir depth --intrinsics intrinsics.json \\
        --scale-from-sparse sparse/0/points3D.txt --out colmap.ply
"""

import json
import os

import numpy as np


# --- 포즈 표현 ---------------------------------------------------------------
# 이 스크립트는 내부적으로 포즈를 **camera→world 4x4 행렬**로 통일해서 다룬다.
# (COLMAP은 world→camera로 저장하므로 읽을 때 뒤집는다 — 자주 틀리는 지점.)

def quat_to_rotation(qw, qx, qy, qz):
    """단위 쿼터니언 → 3x3 회전행렬."""
    n = np.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    if n < 1e-12:
        raise ValueError('영벡터 쿼터니언')
    qw, qx, qy, qz = qw / n, qx / n, qy / n, qz / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ], dtype=np.float64)


def read_colmap_images(path):
    """COLMAP images.txt → {이미지이름: camera→world 4x4}.

    COLMAP은 각 이미지에 `QW QX QY QZ TX TY TZ`를 world→camera(X_cam = R·X_world + T)로
    저장한다. 우리가 원하는 건 반대 방향이므로 R^T와 -R^T·T로 뒤집는다.
    파일은 이미지당 2줄(포즈 줄 + 특징점 줄)이고 '#'로 시작하는 주석이 섞여 있다.
    """
    poses = {}
    with open(path, encoding='utf-8') as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    for i in range(0, len(lines), 2):  # 짝수 줄만 포즈, 홀수 줄은 특징점 목록
        parts = lines[i].split()
        if len(parts) < 10:
            continue
        qw, qx, qy, qz, tx, ty, tz = map(float, parts[1:8])
        name = parts[9]
        r_wc = quat_to_rotation(qw, qx, qy, qz)
        t_wc = np.array([tx, ty, tz], dtype=np.float64)
        m = np.eye(4)
        m[:3, :3] = r_wc.T
        m[:3, 3] = -r_wc.T @ t_wc
        poses[name] = m
    return poses


def read_tum_poses(path):
    """TUM 형식(`timestamp tx ty tz qx qy qz qw`) → {타임스탬프문자열: camera→world 4x4}.

    RTAB-Map의 `rtabmap-export --poses`가 내놓는 궤적을 읽기 위한 것. TUM 형식은
    이미 camera→world라 뒤집지 않는다.
    """
    poses = {}
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            parts = ln.split()
            if len(parts) < 8:
                continue
            stamp = parts[0]
            tx, ty, tz, qx, qy, qz, qw = map(float, parts[1:8])
            m = np.eye(4)
            m[:3, :3] = quat_to_rotation(qw, qx, qy, qz)
            m[:3, 3] = [tx, ty, tz]
            poses[stamp] = m
    return poses


# --- 스케일 복원 -------------------------------------------------------------

def estimate_scale_from_sparse(points3d_path, images_path, depth_lookup):
    """SfM 결과의 미지 스케일을 depth 측정치로 확정한다.

    순수 photogrammetry 결과에는 실제 크기 정보가 없다(형상은 맞는데 2m인지 2cm인지
    모름). 균열을 mm로 재야 하는 이 프로젝트에서는 이걸 반드시 메워야 하고,
    그 역할을 depth 카메라가 한다.

    방법: SfM이 복원한 3D 점 하나하나는 어느 이미지의 어느 픽셀에서 관측됐는지
    알려져 있다. 그 픽셀의 **측정된 depth**와 SfM 좌표계에서의 **카메라-점 거리**를
    비교하면 비율이 곧 스케일이다. 튀는 값(depth 무효, 오매칭)이 섞이므로 평균이
    아니라 **중앙값**을 쓴다 — 8/20 `crack_collector_node`에서 같은 이유로 중앙값을
    택했던 것과 같은 판단.

    depth_lookup(image_name, u, v) -> 미터 단위 depth 또는 None
    """
    cam_from_world = {}
    with open(images_path, encoding='utf-8') as f:
        lines = [ln.rstrip('\n') for ln in f if ln.strip() and not ln.startswith('#')]
    obs = {}  # image_name -> {point3d_id: (u, v)}
    for i in range(0, len(lines), 2):
        parts = lines[i].split()
        if len(parts) < 10:
            continue
        qw, qx, qy, qz, tx, ty, tz = map(float, parts[1:8])
        name = parts[9]
        cam_from_world[name] = (quat_to_rotation(qw, qx, qy, qz),
                                np.array([tx, ty, tz], dtype=np.float64))
        obs[name] = {}
        if i + 1 < len(lines):
            toks = lines[i + 1].split()
            for j in range(0, len(toks) - 2, 3):
                pid = int(toks[j + 2])
                if pid != -1:
                    obs[name][pid] = (float(toks[j]), float(toks[j + 1]))

    xyz = {}
    with open(points3d_path, encoding='utf-8') as f:
        for ln in f:
            if not ln.strip() or ln.startswith('#'):
                continue
            parts = ln.split()
            xyz[int(parts[0])] = np.array(list(map(float, parts[1:4])), dtype=np.float64)

    ratios = []
    for name, (r_wc, t_wc) in cam_from_world.items():
        for pid, (u, v) in obs.get(name, {}).items():
            p = xyz.get(pid)
            if p is None:
                continue
            z_sfm = float((r_wc @ p + t_wc)[2])  # 카메라 광학축 방향 거리(SfM 단위)
            if z_sfm <= 1e-6:
                continue
            z_meas = depth_lookup(name, u, v)
            if z_meas is None or z_meas <= 0:
                continue
            ratios.append(z_meas / z_sfm)

    if len(ratios) < 20:
        raise RuntimeError('스케일 추정에 쓸 대응점이 너무 적다(%d개)' % len(ratios))
    ratios = np.array(ratios)
    return float(np.median(ratios)), len(ratios), float(np.percentile(ratios, 84) -
                                                        np.percentile(ratios, 16))


# --- 역투영 ------------------------------------------------------------------

def deproject(depth_m, fx, fy, cx, cy, stride=1, min_m=0.3, max_m=3.0):
    """depth 이미지(미터) → 카메라 좌표계 3D 점 (N,3).

    min_m 기본 0.3 / max_m 기본 3.0은 이 프로젝트의 촬영 조건에서 온 값이다.
    1번 항목 실측대로 50cm 근처에서는 D455F depth가 실제의 약 2배로 튀고, 멀수록
    오차가 거리²로 커지므로 유효 구간만 남긴다.
    """
    h, w = depth_m.shape
    vs, us = np.mgrid[0:h:stride, 0:w:stride]
    z = depth_m[0:h:stride, 0:w:stride]
    valid = (z > min_m) & (z < max_m) & np.isfinite(z)
    z = z[valid]
    us = us[valid].astype(np.float64)
    vs = vs[valid].astype(np.float64)
    x = (us - cx) * z / fx
    y = (vs - cy) * z / fy
    return np.stack([x, y, z], axis=1)


def transform(points, cam_to_world):
    """카메라 좌표 점들을 world로 옮긴다."""
    if points.size == 0:
        return points
    return points @ cam_to_world[:3, :3].T + cam_to_world[:3, 3]


def write_ply(path, points, colors=None):
    """binary_little_endian PLY로 저장(rtabmap-export 산출물과 같은 형식)."""
    n = len(points)
    header = ['ply', 'format binary_little_endian 1.0', 'element vertex %d' % n,
              'property float x', 'property float y', 'property float z']
    if colors is not None:
        header += ['property uchar red', 'property uchar green', 'property uchar blue']
    header += ['end_header', '']
    with open(path, 'wb') as f:
        f.write('\n'.join(header).encode())
        if colors is None:
            f.write(np.asarray(points, dtype='<f4').tobytes())
        else:
            rec = np.empty(n, dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
                                     ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])
            rec['x'], rec['y'], rec['z'] = points[:, 0], points[:, 1], points[:, 2]
            rec['r'], rec['g'], rec['b'] = colors[:, 0], colors[:, 1], colors[:, 2]
            f.write(rec.tobytes())


def main():
    import argparse
    import cv2

    ap = argparse.ArgumentParser(description='포즈 + depth로 포인트클라우드를 만든다')
    ap.add_argument('--poses', required=True, help='포즈 파일')
    ap.add_argument('--pose-format', choices=['colmap', 'tum'], default='colmap')
    ap.add_argument('--depth-dir', required=True, help='16bit PNG depth 디렉토리(mm 단위)')
    ap.add_argument('--color-dir', help='컬러 이미지 디렉토리(색을 입히려면)')
    ap.add_argument('--intrinsics', required=True, help='intrinsics.json')
    ap.add_argument('--scale-from-sparse', help='COLMAP points3D.txt (스케일 복원용)')
    ap.add_argument('--out', required=True, help='출력 .ply')
    ap.add_argument('--stride', type=int, default=4, help='픽셀 솎기 간격(기본 4)')
    ap.add_argument('--min-m', type=float, default=0.3)
    ap.add_argument('--max-m', type=float, default=3.0)
    args = ap.parse_args()

    with open(args.intrinsics, encoding='utf-8') as f:
        intr = json.load(f)
    fx, fy, cx, cy = intr['fx'], intr['fy'], intr['cx'], intr['cy']
    depth_scale = intr.get('depth_scale_m', 0.001)  # 16bit PNG 1단위 = 1mm

    poses = (read_colmap_images(args.poses) if args.pose_format == 'colmap'
             else read_tum_poses(args.poses))
    print('포즈 %d개 로드' % len(poses))

    def depth_path(name):
        return os.path.join(args.depth_dir, os.path.splitext(name)[0] + '.png')

    scale = 1.0
    if args.scale_from_sparse:
        cache = {}

        def lookup(name, u, v):
            if name not in cache:
                img = cv2.imread(depth_path(name), cv2.IMREAD_UNCHANGED)
                cache[name] = img
                if len(cache) > 40:  # 메모리 보호
                    cache.pop(next(iter(cache)))
            img = cache.get(name)
            if img is None:
                return None
            iu, iv = int(round(u)), int(round(v))
            if not (0 <= iv < img.shape[0] and 0 <= iu < img.shape[1]):
                return None
            d = float(img[iv, iu]) * depth_scale
            return d if d > 0 else None

        scale, n_used, spread = estimate_scale_from_sparse(
            args.scale_from_sparse, args.poses, lookup)
        print('스케일 %.6f (대응점 %d개, 16~84%% 폭 %.4f)' % (scale, n_used, spread))

    clouds, colors = [], []
    for name in sorted(poses):
        d_img = cv2.imread(depth_path(name), cv2.IMREAD_UNCHANGED)
        if d_img is None:
            continue
        pts = deproject(d_img.astype(np.float64) * depth_scale, fx, fy, cx, cy,
                        stride=args.stride, min_m=args.min_m, max_m=args.max_m)
        if pts.size == 0:
            continue
        m = poses[name].copy()
        m[:3, 3] *= scale  # 회전은 스케일과 무관, 이동만 실제 크기로 되돌린다
        clouds.append(transform(pts, m))
        if args.color_dir:
            c_img = cv2.imread(os.path.join(args.color_dir, name))
            if c_img is not None:
                h, w = d_img.shape
                vs, us = np.mgrid[0:h:args.stride, 0:w:args.stride]
                z = d_img.astype(np.float64)[0:h:args.stride, 0:w:args.stride] * depth_scale
                valid = (z > args.min_m) & (z < args.max_m)
                colors.append(c_img[vs[valid], us[valid]][:, ::-1])  # BGR→RGB

    if not clouds:
        raise SystemExit('쌓인 점이 없다 — depth 경로/이름 규칙을 확인할 것')
    allpts = np.vstack(clouds)
    allcol = np.vstack(colors) if colors and len(colors) == len(clouds) else None
    write_ply(args.out, allpts, allcol)
    print('저장: %s (%d점, 프레임 %d개)' % (args.out, len(allpts), len(clouds)))


if __name__ == '__main__':
    main()
