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


def measure_distance_mm(depth_image, depth_scale, intrinsics, point_a, point_b):
    ax, ay = point_a
    bx, by = point_b

    depth_a = float(depth_image[ay, ax]) * depth_scale
    depth_b = float(depth_image[by, bx]) * depth_scale

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
