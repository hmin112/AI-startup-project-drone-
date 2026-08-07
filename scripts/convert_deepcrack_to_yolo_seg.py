"""Convert DeepCrack's binary crack masks (0/255 PNG) into Ultralytics
YOLO-segmentation polygon labels, and lay out images/labels into the
images/{train,val}, labels/{train,val} structure Ultralytics expects.

Each connected crack component in a mask becomes one polygon instance line
(class 0 = crack). Tiny noise contours (area < MIN_CONTOUR_AREA) are
dropped. Coordinates are normalized to [0, 1] by image width/height.
"""
import os
import shutil

import cv2
import numpy as np

SRC_ROOT = os.path.expanduser("~/DeepCrack/dataset/extracted")
DST_ROOT = os.path.expanduser("~/bridge_drone_ws/datasets/deepcrack_yolo")
MIN_CONTOUR_AREA = 15  # px^2, drop tiny speckle noise from the binary mask
SPLITS = [("train", "train"), ("test", "val")]  # DeepCrack split -> YOLO split name


def mask_to_yolo_lines(mask_path, img_width, img_height):
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    lines = []
    for contour in contours:
        if cv2.contourArea(contour) < MIN_CONTOUR_AREA or len(contour) < 3:
            continue
        points = contour.reshape(-1, 2).astype(np.float32)
        points[:, 0] /= img_width
        points[:, 1] /= img_height
        coords = " ".join(f"{x:.6f} {y:.6f}" for x, y in points)
        lines.append(f"0 {coords}")
    return lines


def main():
    total_instances = 0
    total_empty = 0

    for src_split, dst_split in SPLITS:
        img_src_dir = os.path.join(SRC_ROOT, f"{src_split}_img")
        lab_src_dir = os.path.join(SRC_ROOT, f"{src_split}_lab")
        img_dst_dir = os.path.join(DST_ROOT, "images", dst_split)
        lab_dst_dir = os.path.join(DST_ROOT, "labels", dst_split)
        os.makedirs(img_dst_dir, exist_ok=True)
        os.makedirs(lab_dst_dir, exist_ok=True)

        filenames = sorted(f for f in os.listdir(img_src_dir) if f.lower().endswith(".jpg"))
        for filename in filenames:
            stem = os.path.splitext(filename)[0]
            img_path = os.path.join(img_src_dir, filename)
            mask_path = os.path.join(lab_src_dir, f"{stem}.png")

            img = cv2.imread(img_path)
            height, width = img.shape[:2]

            lines = mask_to_yolo_lines(mask_path, width, height)
            if not lines:
                total_empty += 1
            total_instances += len(lines)

            shutil.copy(img_path, os.path.join(img_dst_dir, filename))
            with open(os.path.join(lab_dst_dir, f"{stem}.txt"), "w") as f:
                f.write("\n".join(lines))

        print(f"{src_split} -> {dst_split}: {len(filenames)} images")

    print(f"Total polygon instances: {total_instances}")
    print(f"Images with zero valid instances (empty label file): {total_empty}")

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
