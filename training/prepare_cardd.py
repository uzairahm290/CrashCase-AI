"""Convert CarDD (COCO format) to YOLOv8-seg format.

CarDD: https://cardd-ustc.github.io  (request access; download CarDD_COCO)
Expected input:
    datasets/CarDD_COCO/annotations/instances_{train,val}2017.json
    datasets/CarDD_COCO/{train,val}2017/*.jpg
Output:
    datasets/cardd_yolo/{images,labels}/{train,val}/ + data.yaml

Any COCO-format car damage set (e.g. a Roboflow export) works the same way.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

import yaml


def normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def convert_split(src: Path, out: Path, split: str, coco_split: str) -> dict[int, str]:
    ann = json.loads((src / "annotations" / f"instances_{coco_split}.json").read_text())
    cats = sorted(ann["categories"], key=lambda c: c["id"])
    cat_index = {c["id"]: i for i, c in enumerate(cats)}
    images = {im["id"]: im for im in ann["images"]}

    per_image = defaultdict(list)
    for a in ann["annotations"]:
        if a.get("iscrowd") or not isinstance(a.get("segmentation"), list):
            continue  # RLE masks are rare in CarDD; skip them
        per_image[a["image_id"]].append(a)

    (out / "images" / split).mkdir(parents=True, exist_ok=True)
    (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    for img_id, im in images.items():
        w, h = im["width"], im["height"]
        lines = []
        for a in per_image.get(img_id, []):
            for poly in a["segmentation"]:
                if len(poly) < 6:
                    continue
                coords = [f"{(v / w if i % 2 == 0 else v / h):.6f}" for i, v in enumerate(poly)]
                lines.append(f"{cat_index[a['category_id']]} " + " ".join(coords))
        stem = Path(im["file_name"]).stem
        shutil.copy2(src / coco_split / im["file_name"], out / "images" / split / im["file_name"])
        (out / "labels" / split / f"{stem}.txt").write_text("\n".join(lines))
    return {i: normalize(c["name"]) for i, c in enumerate(cats)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="datasets/CarDD_COCO")
    p.add_argument("--out", default="datasets/cardd_yolo")
    args = p.parse_args()
    src, out = Path(args.src), Path(args.out)

    names = convert_split(src, out, "train", "train2017")
    convert_split(src, out, "val", "val2017")
    (out / "data.yaml").write_text(
        yaml.safe_dump(
            {"path": str(out.resolve()), "train": "images/train", "val": "images/val", "names": names}
        )
    )
    print(f"wrote {out}/data.yaml with classes {list(names.values())}")


if __name__ == "__main__":
    main()
