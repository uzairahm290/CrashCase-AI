"""Schema and quality checks on the raw COCO dataset. Runs before anything else in `dvc repro`.

    python training/validate_data.py --src datasets/CarDD_COCO --out reports/data_validation.json

Exits non-zero, which stops the DVC pipeline, when:
  - an annotation file is missing, is not valid JSON, or lacks images/annotations/categories
  - the class list differs between splits or from `validate.classes` in params.yaml
  - an image file is missing, cannot be decoded, or its size disagrees with the annotation
  - an annotation points at an unknown image or category
  - more than `validate.max_bad_annotation_frac` of a split's annotations are malformed
    (bad bbox, polygon with an odd or too-short coordinate list, coordinates outside the image)
  - a split has fewer than `validate.min_images` images, or a class never appears in train
  - the same file name appears in two splits

Everything else (images with no damage labelled, a class missing from val/test) is a warning.
The full report is written to --out either way, so a failed run still shows what broke.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image

SPLITS = ("train2017", "val2017", "test2017")
SAMPLE = 20  # how many offending items to keep per problem in the report
EDGE = 2.0  # pixels of slack for coordinates that sit on the image border


class Report:
    def __init__(self) -> None:
        self.errors: dict[str, list[str]] = {}
        self.warnings: dict[str, list[str]] = {}
        self.counts: Counter = Counter()
        self.stats: dict = {}

    def _add(self, bucket: dict, key: str, item: str) -> None:
        self.counts[key] += 1
        items = bucket.setdefault(key, [])
        if len(items) < SAMPLE:
            items.append(item)

    def error(self, key: str, item: str) -> None:
        self._add(self.errors, key, item)

    def warn(self, key: str, item: str) -> None:
        self._add(self.warnings, key, item)

    def to_dict(self) -> dict:
        return {
            "passed": not self.errors,
            "errors": {k: {"count": self.counts[k], "examples": v} for k, v in self.errors.items()},
            "warnings": {k: {"count": self.counts[k], "examples": v} for k, v in self.warnings.items()},
            "stats": self.stats,
        }


def _is_num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def bad_annotation_reason(a: dict, w: int, h: int) -> str | None:
    """Why this annotation is unusable, or None if it is fine."""
    bbox = a.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4 and all(_is_num(v) for v in bbox)):
        return "bbox is not four numbers"
    x, y, bw, bh = bbox
    if bw <= 0 or bh <= 0:
        return "bbox has zero or negative size"
    if x < -EDGE or y < -EDGE or x + bw > w + EDGE or y + bh > h + EDGE:
        return "bbox outside the image"
    seg = a.get("segmentation")
    if a.get("iscrowd"):
        return None  # RLE crowd masks are skipped by the converter, not an error
    if not (isinstance(seg, list) and seg):
        return "no polygon"
    for poly in seg:
        if not (isinstance(poly, list) and all(_is_num(v) for v in poly)):
            return "polygon is not a list of numbers"
        if len(poly) < 6 or len(poly) % 2:
            return "polygon needs an even number of coordinates, at least 3 points"
        xs, ys = poly[0::2], poly[1::2]
        if min(xs) < -EDGE or min(ys) < -EDGE or max(xs) > w + EDGE or max(ys) > h + EDGE:
            return "polygon outside the image"
    return None


def check_image(path: Path, w: int, h: int) -> str | None:
    if not path.exists():
        return "missing"
    try:
        with Image.open(path) as im:
            size = im.size
            im.load()  # verify() skips the pixel data; load() catches truncated files
    except Exception as e:  # noqa: BLE001 - any decode failure means a corrupt file
        return f"cannot decode ({type(e).__name__})"
    if size != (w, h):
        return f"size {size[0]}x{size[1]} but annotation says {w}x{h}"
    return None


def validate_split(src: Path, split: str, cfg: dict, rep: Report, check_images: bool) -> dict | None:
    ann_path = src / "annotations" / f"instances_{split}.json"
    if not ann_path.exists():
        rep.error("annotation_file_missing", str(ann_path))
        return None
    try:
        ann = json.loads(ann_path.read_text())
    except json.JSONDecodeError as e:
        rep.error("annotation_file_invalid_json", f"{ann_path}: {e}")
        return None
    missing = [k for k in ("images", "annotations", "categories") if not isinstance(ann.get(k), list)]
    if missing:
        rep.error("annotation_file_missing_keys", f"{ann_path}: {missing}")
        return None

    cats = {c.get("id"): c.get("name") for c in ann["categories"]}
    images: dict = {}
    for im in ann["images"]:
        ok = (
            isinstance(im.get("id"), int)
            and isinstance(im.get("file_name"), str)
            and isinstance(im.get("width"), int)
            and isinstance(im.get("height"), int)
            and im["width"] > 0
            and im["height"] > 0
        )
        if not ok:
            rep.error("image_record_malformed", f"{split}: {im}")
            continue
        if im["id"] in images:
            rep.error("image_id_duplicate", f"{split}: id {im['id']}")
            continue
        images[im["id"]] = im
        if check_images:
            reason = check_image(src / split / im["file_name"], im["width"], im["height"])
            if reason:
                rep.error("image_file_" + reason.split(" ")[0], f"{split}/{im['file_name']}: {reason}")

    per_image = Counter()
    per_class = Counter()
    ann_ids: set = set()
    bad = 0
    for a in ann["annotations"]:
        if a.get("id") in ann_ids:
            rep.error("annotation_id_duplicate", f"{split}: id {a.get('id')}")
        ann_ids.add(a.get("id"))
        im = images.get(a.get("image_id"))
        if im is None:
            rep.error("annotation_unknown_image", f"{split}: annotation {a.get('id')}")
            continue
        if a.get("category_id") not in cats:
            rep.error("annotation_unknown_category", f"{split}: annotation {a.get('id')}")
            continue
        reason = bad_annotation_reason(a, im["width"], im["height"])
        if reason:
            bad += 1
            rep.warn("annotation_malformed", f"{split}: annotation {a.get('id')}: {reason}")
            continue
        per_image[a["image_id"]] += 1
        per_class[cats[a["category_id"]]] += 1

    n_ann = len(ann["annotations"])
    if n_ann and bad / n_ann > cfg["max_bad_annotation_frac"]:
        rep.error(
            "too_many_malformed_annotations",
            f"{split}: {bad}/{n_ann} = {bad / n_ann:.1%} > {cfg['max_bad_annotation_frac']:.1%}",
        )
    if len(images) < cfg["min_images"]:
        rep.error("split_too_small", f"{split}: {len(images)} images < {cfg['min_images']}")
    for img_id, im in images.items():
        if per_image[img_id] == 0:
            rep.warn("image_without_labels", f"{split}/{im['file_name']}")

    return {
        "categories": cats,
        "file_names": {im["file_name"] for im in images.values()},
        "stats": {
            "images": len(images),
            "annotations": n_ann,
            "malformed_annotations": bad,
            "images_without_labels": sum(1 for i in images if per_image[i] == 0),
            "class_counts": dict(sorted(per_class.items())),
        },
    }


def validate(src: Path, cfg: dict, check_images: bool = True) -> Report:
    rep = Report()
    results = {s: validate_split(src, s, cfg, rep, check_images) for s in SPLITS}
    results = {s: r for s, r in results.items() if r is not None}

    expected = sorted(cfg["classes"])
    for split, r in results.items():
        names = sorted(r["categories"].values())
        if names != expected:
            rep.error("class_list_mismatch", f"{split}: {names} != expected {expected}")
    cat_maps = {json.dumps(sorted(r["categories"].items())) for r in results.values()}
    if len(cat_maps) > 1:
        rep.error("category_ids_differ_between_splits", str([r["categories"] for r in results.values()]))

    for split, r in results.items():
        present = set(r["stats"]["class_counts"])
        for cls in expected:
            if cls not in present:
                (rep.error if split == "train2017" else rep.warn)(
                    "class_absent_from_split", f"{split}: no '{cls}' annotations"
                )

    splits = list(results)
    for i, a in enumerate(splits):
        for b in splits[i + 1 :]:
            for name in sorted(results[a]["file_names"] & results[b]["file_names"]):
                rep.error("file_name_in_two_splits", f"{name} in {a} and {b}")

    rep.stats = {s: r["stats"] for s, r in results.items()}
    return rep


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="datasets/CarDD_COCO")
    p.add_argument("--out", default="reports/data_validation.json")
    p.add_argument("--params", default="params.yaml")
    p.add_argument("--skip-image-decode", action="store_true", help="schema checks only (fast)")
    args = p.parse_args()

    cfg = yaml.safe_load(Path(args.params).read_text())["validate"]
    rep = validate(Path(args.src), cfg, check_images=not args.skip_image_decode)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2))

    for split, s in rep.stats.items():
        print(f"{split}: {s['images']} images, {s['annotations']} annotations, {s['class_counts']}")
    for k, v in rep.to_dict()["warnings"].items():
        print(f"WARNING {k}: {v['count']}  e.g. {v['examples'][:2]}")
    if rep.errors:
        for k, v in rep.to_dict()["errors"].items():
            print(f"ERROR {k}: {v['count']}  e.g. {v['examples'][:3]}", file=sys.stderr)
        print(f"data validation FAILED, see {out}", file=sys.stderr)
        return 1
    print(f"data validation passed, report in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
