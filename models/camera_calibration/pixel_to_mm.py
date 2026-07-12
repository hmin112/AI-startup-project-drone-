"""Convert a pixel-space distance on the D455F depth image into a real-world
millimeter distance, using the depth frame + camera intrinsics.

Core function: measure_distance_mm(depth_frame, intrinsics, point_a, point_b)
  point_a, point_b: (x, y) pixel coordinates (ints)
  returns: real-world distance in millimeters between the two points

This is the building block for crack-size quantification: feed it the two
endpoints of a detected crack (in pixel space) and it returns the real length.
Uses proper 3D deprojection (rs2_deproject_pixel_to_point) rather than a flat
"same depth" assumption, since the two points can sit at different depths on
an angled or uneven surface.
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


def _find_same_surface_pair(depth_image, min_px=80, max_px=150, max_depth_diff_ratio=0.05):
    """Demo helper: scan the depth image for two points min_px~max_px apart
    that sit on the same surface (similar depth), so the distance test is
    representative of measuring a small crack rather than two unrelated objects."""
    h, w = depth_image.shape
    for row in range(50, h - 50, 10):
        line = depth_image[row, :]
        valid_idx = (line > 0).nonzero()[0]
        if len(valid_idx) < 2:
            continue
        for ca in valid_idx:
            candidates = valid_idx[(valid_idx - ca >= min_px) & (valid_idx - ca <= max_px)]
            if len(candidates) == 0:
                continue
            cb = candidates[0]
            da, db = int(line[ca]), int(line[cb])
            if da == 0 or db == 0:
                continue
            if abs(da - db) / max(da, db) < max_depth_diff_ratio:
                return row, int(ca), int(cb)
    return None


if __name__ == "__main__":
    import numpy as np
    import cv2

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 1280, 800, rs.format.bgr8, 30)
    profile = pipeline.start(config)

    try:
        for _ in range(30):
            frames = pipeline.wait_for_frames()

        depth_frame = frames.get_depth_frame()
        intrinsics = depth_frame.profile.as_video_stream_profile().get_intrinsics()
        depth_image = np.asanyarray(depth_frame.get_data())

        found = _find_same_surface_pair(depth_image)
        if not found:
            print("No same-surface point pair found in this frame (scene may be too cluttered).")
        else:
            row, ca, cb = found
            point_a, point_b = (ca, row), (cb, row)

            print(f"Point A: {point_a}, depth={depth_frame.get_distance(*point_a):.3f} m")
            print(f"Point B: {point_b}, depth={depth_frame.get_distance(*point_b):.3f} m")
            print(f"Pixel distance: {abs(cb - ca)} px")

            distance_mm = measure_distance_mm(depth_frame, intrinsics, point_a, point_b)
            print(f"\n[Proper 3D deprojection] Distance: {distance_mm:.1f} mm")

            depth_a = depth_frame.get_distance(*point_a)
            simple_mm = (abs(cb - ca) / intrinsics.fx) * depth_a * 1000.0
            print(f"[Simple flat-plane approx] Distance: {simple_mm:.1f} mm")
            print(f"Difference between methods: {abs(distance_mm - simple_mm) / distance_mm * 100:.1f}%")

            depth_colormap = np.asanyarray(rs.colorizer().colorize(depth_frame).get_data())
            cv2.circle(depth_colormap, point_a, 6, (255, 255, 255), -1)
            cv2.circle(depth_colormap, point_b, 6, (255, 255, 255), -1)
            cv2.line(depth_colormap, point_a, point_b, (255, 255, 255), 2)
            cv2.putText(depth_colormap, f"{distance_mm:.1f} mm", (min(ca, cb), max(row - 20, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.imwrite("/tmp/pixel_to_mm_demo.png", depth_colormap)
            print("\nSaved visualization to /tmp/pixel_to_mm_demo.png")
    finally:
        pipeline.stop()
