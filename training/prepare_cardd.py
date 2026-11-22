"""Convert CarDD (COCO format) to YOLOv8-seg format.

CarDD: https://cardd-ustc.github.io  (request access; download CarDD_COCO)
Expected input:
    datasets/CarDD_COCO/annotations/instances_{train,val,test}2017.json
    datasets/CarDD_COCO/{train,val,test}2017/*.jpg
    reports/leakage.json   (from check_leakage.py: images to drop so no photo spans two splits)
Output:
    datasets/cardd_yolo/{images,labels}/{train,val,test}/ + data.yaml

The splits are CarDD's own, minus the near-duplicates check_leakage.py found. train is for
fitting, val for early stopping and choosing between runs, test is only read once per run, for
the numbers that get reported.

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


def convert_split(
    src: Path, out: Path, split: str, coco_split: str, exclude: frozenset[str] = frozenset()
) -> dict[int, str]:
    ann = json.loads((src / "annotations" / f"instances_{coco_split}.json").read_text())
    cats = sorted(ann["categories"], key=lambda c: c["id"])
    cat_index = {c["id"]: i for i, c in enumerate(cats)}
    images = {im["id"]: im for im in ann["images"] if im["file_name"] not in exclude}

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
    p.add_argument("--leakage", default="reports/leakage.json")
    args = p.parse_args()
    src, out = Path(args.src), Path(args.out)

    leakage = json.loads(Path(args.leakage).read_text())
    if not leakage.get("passed"):
        raise SystemExit(f"{args.leakage} says the leakage check failed; fix the splits first")
    exclude = {s: frozenset(v) for s, v in leakage["exclude"].items()}

    if out.exists():
        shutil.rmtree(out)  # stale files from an earlier exclusion list must not survive
    names = convert_split(src, out, "train", "train2017", exclude.get("train", frozenset()))
    for split in ("val", "test"):
        if convert_split(src, out, split, f"{split}2017", exclude.get(split, frozenset())) != names:
            raise SystemExit(f"{split} has different classes from train")
    (out / "data.yaml").write_text(
        yaml.safe_dump(
            {
                "path": str(out.resolve()),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": names,
            }
        )
    )
    counts = {s: len(list((out / "images" / s).iterdir())) for s in ("train", "val", "test")}
    print(f"images per split after leakage exclusions: {counts}")
    print(f"wrote {out}/data.yaml with classes {list(names.values())}")


if __name__ == "__main__":
    main()
