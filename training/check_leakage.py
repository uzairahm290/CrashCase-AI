"""Find photos shared between splits and decide which copies to drop, before conversion.

    python training/check_leakage.py --src datasets/CarDD_COCO --out reports/leakage.json

CarDD's images are scraped from the web, so the same car photo can turn up in train and in
test, re-encoded or resized. A model that saw it in training gets it right in test for free.

Every image gets a 256-bit difference hash (the same algorithm as the duplicate-photo fraud
check in src/crashcase/pipeline/fraud.py) and an MD5 of its bytes. Pairs across splits within
`leakage.max_hamming` bits are near-duplicates. The rule protects the evaluation splits:

    test is never touched
    val  loses any image that matches a test image
    train loses any image that matches a val or test image

prepare_cardd.py reads the `exclude` lists from the report. The run fails if a split would lose
more than `leakage.max_excluded_frac` of its images: at that point the split itself is broken
and quietly dropping images would hide it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

SPLITS = {"train": "train2017", "val": "val2017", "test": "test2017"}
# Which split loses its copy when two splits share a photo: the one less important to evaluation.
LOSER = {("train", "val"): "train", ("train", "test"): "train", ("val", "test"): "val"}
_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def dhash_bits(path: Path, size: int = 16) -> np.ndarray:
    """Packed 256-bit difference hash: 32 bytes."""
    with Image.open(path) as im:
        im.draft("L", (size * 4, size * 4))  # let the JPEG decoder downscale; much faster
        g = np.asarray(im.convert("L").resize((size + 1, size)), dtype=np.int16)
    return np.packbits((g[:, 1:] > g[:, :-1]).ravel())


def hamming_matrix(a: np.ndarray, b: np.ndarray, chunk: int = 256) -> np.ndarray:
    """All pairwise Hamming distances between packed hashes a (n,32) and b (m,32)."""
    out = np.empty((len(a), len(b)), dtype=np.uint16)
    for i in range(0, len(a), chunk):
        x = a[i : i + chunk, None, :] ^ b[None, :, :]
        out[i : i + chunk] = _POPCOUNT[x].sum(axis=2, dtype=np.uint16)
    return out


def load_split(src: Path, coco_split: str) -> tuple[list[str], np.ndarray, list[str]]:
    ann = json.loads((src / "annotations" / f"instances_{coco_split}.json").read_text())
    names = sorted(im["file_name"] for im in ann["images"])
    hashes = np.stack([dhash_bits(src / coco_split / n) for n in names])
    md5s = [hashlib.md5((src / coco_split / n).read_bytes()).hexdigest() for n in names]
    return names, hashes, md5s


def find_leaks(splits: dict[str, tuple[list[str], np.ndarray, list[str]]], max_hamming: int) -> dict:
    exclude: dict[str, set[str]] = {s: set() for s in splits}
    pairs = []
    min_dist = {}
    for (a, b), loser in LOSER.items():
        if a not in splits or b not in splits:
            continue
        na, ha, ma = splits[a]
        nb, hb, mb = splits[b]
        d = hamming_matrix(ha, hb)
        min_dist[f"{a}-{b}"] = d.min(axis=1).tolist()
        md5_b = {m: n for n, m in zip(nb, mb, strict=True)}
        for i, j in zip(*np.nonzero(d <= max_hamming), strict=True):
            pairs.append({"a": f"{a}/{na[i]}", "b": f"{b}/{nb[j]}", "distance": int(d[i, j])})
            exclude[loser].add(na[i] if loser == a else nb[j])
        for n, m in zip(na, ma, strict=True):  # byte-identical files: always a leak
            if m in md5_b:
                pairs.append({"a": f"{a}/{n}", "b": f"{b}/{md5_b[m]}", "distance": 0, "identical": True})
                exclude[loser].add(n if loser == a else md5_b[m])
    return {"exclude": exclude, "pairs": pairs, "min_dist": min_dist}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="datasets/CarDD_COCO")
    p.add_argument("--out", default="reports/leakage.json")
    p.add_argument("--params", default="params.yaml")
    args = p.parse_args()
    cfg = yaml.safe_load(Path(args.params).read_text())["leakage"]
    src = Path(args.src)

    splits = {s: load_split(src, c) for s, c in SPLITS.items()}
    found = find_leaks(splits, cfg["max_hamming"])

    report = {
        "max_hamming": cfg["max_hamming"],
        "policy": "test untouched; val loses matches of test; train loses matches of val or test",
        "images_before": {s: len(v[0]) for s, v in splits.items()},
        "excluded_count": {s: len(found["exclude"][s]) for s in splits},
        "images_after": {s: len(splits[s][0]) - len(found["exclude"][s]) for s in splits},
        "cross_split_pairs": len(found["pairs"]),
        # How close each image's nearest neighbour in the other split is: shows the margin
        # between the threshold and genuinely different photos.
        "nearest_distance_percentiles": {
            k: {q: int(np.percentile(v, q)) for q in (0, 1, 5, 50)} for k, v in found["min_dist"].items()
        },
        "exclude": {s: sorted(v) for s, v in found["exclude"].items()},
        "pairs": sorted(found["pairs"], key=lambda x: x["distance"]),
    }

    failed = []
    for s, n in report["excluded_count"].items():
        frac = n / report["images_before"][s]
        if frac > cfg["max_excluded_frac"]:
            failed.append(f"{s}: {n} images ({frac:.1%}) duplicate another split")
    report["passed"] = not failed

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"cross-split near-duplicate pairs (<= {cfg['max_hamming']} bits): {len(found['pairs'])}")
    print(f"excluded: {report['excluded_count']}  ->  remaining: {report['images_after']}")
    print(f"nearest-neighbour distance percentiles: {report['nearest_distance_percentiles']}")
    if failed:
        print("leakage check FAILED: " + "; ".join(failed), file=sys.stderr)
        return 1
    print(f"leakage check passed, report in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
