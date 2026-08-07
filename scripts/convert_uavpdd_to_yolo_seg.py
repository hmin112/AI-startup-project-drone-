"""Convert UAV-PDD2023's PASCAL VOC bounding boxes into YOLO-segmentation
"polygon" labels — since there are no real masks, each bbox becomes a
4-corner rectangle polygon. Only the four crack subtypes are kept
(Longitudinal/Transverse/Oblique/Alligator crack -> class 0 "crack");
Pothole/Repair objects are dropped (out of scope for this project's
single-class crack-seg model). Images that end up with zero crack
instances are still included as background images (empty label file),
which Ultralytics treats as valid negative examples.

This is a known-lossy conversion: a rectangle is a poor stand-in for a
crack's actual long/thin/diagonal shape (exactly why segmentation was
chosen over bbox measurement in the first place, see
vision_ai/measurement.py and docs/jetson_setup_log.md's 7/13 findings) -
being tried anyway because UAV-PDD2023 is real 30m-altitude drone
imagery, which no other available dataset has. Effectiveness must be
checked against a baseline the same way the DeepCrack fine-tune was.
"""
import os
import shutil
import xml.etree.ElementTree as ET

SRC_ROOT = os.path.expanduser("~/uav_pdd2023/extracted")
DST_ROOT = os.path.expanduser("~/bridge_drone_ws/datasets/uavpdd_yolo")
CRACK_CLASSES = {"Longitudinal crack", "Transverse crack", "Oblique crack", "Alligator crack"}
SPLITS = [("train", "train"), ("val", "val")]  # VOC split -> YOLO split name


def xml_to_yolo_lines(xml_path, img_width, img_height):
    tree = ET.parse(xml_path)
    lines = []
    for obj in tree.getroot().findall("object"):
        name = obj.findtext("name")
        if name not in CRACK_CLASSES:
            continue
        box = obj.find("bndbox")
        xmin = float(box.findtext("xmin"))
        ymin = float(box.findtext("ymin"))
        xmax = float(box.findtext("xmax"))
        ymax = float(box.findtext("ymax"))

        corners = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
        coords = " ".join(f"{x / img_width:.6f} {y / img_height:.6f}" for x, y in corners)
        lines.append(f"0 {coords}")
    return lines


def main():
    total_instances = 0
    total_background = 0

    for split_file, dst_split in SPLITS:
        ids_path = os.path.join(SRC_ROOT, "ImageSets", "Main", f"{split_file}.txt")
        with open(ids_path) as f:
            stems = [line.strip() for line in f if line.strip()]

        img_dst_dir = os.path.join(DST_ROOT, "images", dst_split)
        lab_dst_dir = os.path.join(DST_ROOT, "labels", dst_split)
        os.makedirs(img_dst_dir, exist_ok=True)
        os.makedirs(lab_dst_dir, exist_ok=True)

        for stem in stems:
            img_path = os.path.join(SRC_ROOT, "JPEGImages", f"{stem}.jpg")
            xml_path = os.path.join(SRC_ROOT, "Annotations", f"{stem}.xml")
            if not os.path.exists(img_path) or not os.path.exists(xml_path):
                continue

            tree = ET.parse(xml_path)
            size = tree.getroot().find("size")
            width = float(size.findtext("width"))
            height = float(size.findtext("height"))

            lines = xml_to_yolo_lines(xml_path, width, height)
            if not lines:
                total_background += 1
            total_instances += len(lines)

            shutil.copy(img_path, os.path.join(img_dst_dir, f"{stem}.jpg"))
            with open(os.path.join(lab_dst_dir, f"{stem}.txt"), "w") as f:
                f.write("\n".join(lines))

        print(f"{split_file} -> {dst_split}: {len(stems)} images")

    print(f"Total crack polygon instances: {total_instances}")
    print(f"Background images (no crack instances): {total_background}")

    yaml_content = f"""path: {DST_ROOT}
train: images/train
val: images/val
names:
  0: crack
"""
    with open(os.path.join(DST_ROOT, "data.yaml"), "w") as f:
        f.write(yaml_content)
    print(f"Wrote {os.path.join(DST_ROOT, 'data.yaml')}")


if __name__ == "__main__":
    main()
