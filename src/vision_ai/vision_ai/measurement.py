"""Convert a pixel-space distance on the D455F depth image into a real-world
millimeter distance, using the depth frame + camera intrinsics.

Ported from models/camera_calibration/pixel_to_mm.py (verified on-device:
proper 3D deprojection vs. flat-plane approximation differed by 20% on an
angled surface, and 60-70% across unrelated objects) with no logic changes.
"""
import pyrealsense2 as rs


def measure_distance_mm(depth_frame, intrinsics, point_a, point_b):
    ax, ay = point_a
    bx, by = point_b

    depth_a = depth_frame.get_distance(ax, ay)
    depth_b = depth_frame.get_distance(bx, by)

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
