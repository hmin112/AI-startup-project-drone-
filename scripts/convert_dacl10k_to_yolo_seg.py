"""Convert dacl10k's labelme-format "Crack" polygon annotations into
Ultralytics YOLO-segmentation labels (class 0 = crack). dacl10k is a
19-class multi-label semantic segmentation dataset (13 damage + 6 object
classes) for real-world bridge inspection images - only the "Crack"
class is extracted here, everything else (Rust, Spalling, ACrack/
alligator crack, etc.) is dropped since this project's model is
single-class.

Only images that contain at least one Crack shape are used (dacl10k is
multi-label and most images don't have visible cracks - including all
~6900 train images would mostly add pure-background examples of limited
value for this project's already-established crack model).
"""
import json
import os
import shutil

SRC_ROOT = os.path.expanduser("~/dacl10k/extracted/dacl10k_v2_devphase")
DST_ROOT = os.path.expanduser("~/bridge_drone_ws/datasets/dacl10k_yolo")
SPLITS = [("train", "train"), ("validation", "val")]  # dacl10k split -> YOLO split name


def annotation_to_yolo_lines(ann_path):
    with open(ann_path) as f:
        ann = json.load(f)

    width = ann["imageWidth"]
    height = ann["imageHeight"]

    lines = []
    for shape in ann["shapes"]:
        if shape["label"] != "Crack":
            continue
        points = shape["points"]
        if len(points) < 3:
            continue
        coords = " ".join(f"{x / width:.6f} {y / height:.6f}" for x, y in points)
        lines.append(f"0 {coords}")
    return lines, ann["imageName"]


def main():
    total_instances = 0

    for src_split, dst_split in SPLITS:
        ann_dir = os.path.join(SRC_ROOT, "annotations", src_split)
        img_dir = os.path.join(SRC_ROOT, "images", src_split)
        img_dst_dir = os.path.join(DST_ROOT, "images", dst_split)
        lab_dst_dir = os.path.join(DST_ROOT, "labels", dst_split)
        os.makedirs(img_dst_dir, exist_ok=True)
        os.makedirs(lab_dst_dir, exist_ok=True)

        copied = 0
        for filename in sorted(os.listdir(ann_dir)):
            if not filename.endswith(".json"):
                continue
            ann_path = os.path.join(ann_dir, filename)
            lines, image_name = annotation_to_yolo_lines(ann_path)
            if not lines:
                continue  # crack 없는 이미지는 스킵(위 docstring 참고)

            img_path = os.path.join(img_dir, image_name)
            if not os.path.exists(img_path):
                print(f"WARNING: missing image {img_path}, skipping")
                continue

            stem = os.path.splitext(image_name)[0]
            shutil.copy(img_path, os.path.join(img_dst_dir, image_name))
            with open(os.path.join(lab_dst_dir, f"{stem}.txt"), "w") as f:
                f.write("\n".join(lines))

            total_instances += len(lines)
            copied += 1

        print(f"{src_split} -> {dst_split}: {copied} images with Crack annotations")

    print(f"Total crack polygon instances: {total_instances}")

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
