import pyrealsense2 as rs
import json

pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 1280, 800, rs.format.bgr8, 30)

profile = pipeline.start(config)

def intrinsics_to_dict(intr):
    return {
        "width": intr.width,
        "height": intr.height,
        "fx": intr.fx,
        "fy": intr.fy,
        "ppx": intr.ppx,
        "ppy": intr.ppy,
        "model": str(intr.model),
        "coeffs": list(intr.coeffs),
    }

try:
    depth_stream = profile.get_stream(rs.stream.depth).as_video_stream_profile()
    color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()

    depth_intr = depth_stream.get_intrinsics()
    color_intr = color_stream.get_intrinsics()

    depth_to_color = depth_stream.get_extrinsics_to(color_stream)

    depth_sensor = profile.get_device().first_depth_sensor()
    depth_scale = depth_sensor.get_depth_scale()

    result = {
        "depth_intrinsics": intrinsics_to_dict(depth_intr),
        "color_intrinsics": intrinsics_to_dict(color_intr),
        "depth_to_color_extrinsics": {
            "rotation": list(depth_to_color.rotation),
            "translation": list(depth_to_color.translation),
        },
        "depth_scale_m_per_unit": depth_scale,
        "device_serial": profile.get_device().get_info(rs.camera_info.serial_number),
        "firmware_version": profile.get_device().get_info(rs.camera_info.firmware_version),
    }

    print(json.dumps(result, indent=2))

    with open("/tmp/d455f_intrinsics.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nSaved to /tmp/d455f_intrinsics.json")
finally:
    pipeline.stop()
