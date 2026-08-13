"""Convert a pixel-space distance on the D455F depth image into a real-world
millimeter distance, using a depth image + camera intrinsics.

Ported from models/camera_calibration/pixel_to_mm.py (verified on-device:
proper 3D deprojection vs. flat-plane approximation differed by 20% on an
angled surface, and 60-70% across unrelated objects). The deprojection/
distance math is unchanged from that validation — only the depth lookup
source changed, from a live pyrealsense2 depth_frame to a raw depth image
array + depth_scale, once vision_ai stopped opening the D455F directly and
started subscribing to realsense2_camera's topics instead (D455F is now a
single shared capture point, see vision_ai_node.py).
"""
import pyrealsense2 as rs

# 균열/틈의 경계는 depth 센서가 가장 취약한 지점(어둡거나 급격한 단차)이라,
# 측정에 쓰는 픽셀이 정확히 그 경계에 걸리면 depth=0(무효)이 되기 쉽다.
# 2026-08-13 실측(젯슨+D455F, 실제 벽 틈): bbox 4개 모서리 중점 중 3개가
# depth=0으로 측정 자체가 통째로 실패 — 주변 픽셀까지 찾아보는 폴백 추가.
_DEPTH_SEARCH_RADIUS_PX = 5


def _nearest_valid_depth(depth_image, point):
    """point의 depth가 무효(0)면 주변을 링 단위로 넓혀가며 가장 가까운
    유효 depth 픽셀을 찾는다. 못 찾으면 (0, point)를 반환."""
    x, y = point
    height, width = depth_image.shape
    if depth_image[y, x] != 0:
        return float(depth_image[y, x]), (x, y)

    for radius in range(1, _DEPTH_SEARCH_RADIUS_PX + 1):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue  # 이전 radius에서 이미 검사한 픽셀은 건너뜀
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and depth_image[ny, nx] != 0:
                    return float(depth_image[ny, nx]), (nx, ny)

    return 0.0, point


def deproject_point_m(depth_image, depth_scale, intrinsics, point):
    """단일 픽셀을 카메라 광학 프레임 기준 3D 좌표(미터)로 역투영.

    2D 탐지를 3D 지도에 태깅하려면(크랙 태깅/퓨전, crack_fusion_node.py
    참고) 크기(mm)뿐 아니라 위치 자체도 필요해서 분리한 헬퍼 — 아래
    measure_distance_mm()과 같은 rs2_deproject_pixel_to_point 호출을
    재사용한다.
    """
    raw_depth, (x, y) = _nearest_valid_depth(depth_image, point)
    depth = raw_depth * depth_scale
    if depth == 0:
        return None
    return rs.rs2_deproject_pixel_to_point(intrinsics, [x, y], depth)


def measure_distance_mm(depth_image, depth_scale, intrinsics, point_a, point_b):
    raw_depth_a, (ax, ay) = _nearest_valid_depth(depth_image, point_a)
    raw_depth_b, (bx, by) = _nearest_valid_depth(depth_image, point_b)
    depth_a = raw_depth_a * depth_scale
    depth_b = raw_depth_b * depth_scale

    if depth_a == 0 or depth_b == 0:
        raise ValueError(
            f"Invalid (zero) depth at one of the points: "
            f"a={point_a} depth={depth_a}, b={point_b} depth={depth_b}"
        )

    point_3d_a = rs.rs2_deproject_pixel_to_point(intrinsics, [ax, ay], depth_a)
    point_3d_b = rs.rs2_deproject_pixel_to_point(intrinsics, [bx, by], depth_b)

    dx = point_3d_a[0] - point_3d_b[0]
    dy = point_3d_a[1] - point_3d_b[1]
    dz = point_3d_a[2] - point_3d_b[2]
    distance_m = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5

    return distance_m * 1000.0
