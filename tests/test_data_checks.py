"""The pre-training data gates: schema/quality validation and cross-split leakage."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "training"))

from check_leakage import find_leaks, load_split  # noqa: E402
from validate_data import validate  # noqa: E402

CLASSES = ["dent", "scratch"]
CFG = {"classes": CLASSES, "min_images": 2, "max_bad_annotation_frac": 0.0}


def _photo(seed: int) -> Image.Image:
    # Smooth random blobs, so different seeds give genuinely different difference hashes.
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, size=(6, 8, 3)).astype(np.uint8)
    return Image.fromarray(small).resize((80, 60), Image.BICUBIC)


def make_coco(root: Path, seeds: dict[str, list[int]]) -> Path:
    (root / "annotations").mkdir(parents=True)
    cats = [{"id": i + 1, "name": n} for i, n in enumerate(CLASSES)]
    for split, split_seeds in seeds.items():
        (root / split).mkdir()
        images, anns = [], []
        for k, seed in enumerate(split_seeds):
            name = f"{split}_{k}.jpg"
            _photo(seed).save(root / split / name, quality=95)
            images.append({"id": k + 1, "file_name": name, "width": 80, "height": 60})
            for c in (1, 2):
                anns.append(
                    {
                        "id": len(anns) + 1,
                        "image_id": k + 1,
                        "category_id": c,
                        "bbox": [10, 10, 20, 20],
                        "segmentation": [[10, 10, 30, 10, 30, 30, 10, 30]],
                        "area": 400,
                        "iscrowd": 0,
                    }
                )
        doc = {"images": images, "annotations": anns, "categories": cats}
        (root / "annotations" / f"instances_{split}.json").write_text(json.dumps(doc))
    return root


@pytest.fixture
def coco(tmp_path):
    return make_coco(tmp_path / "coco", {"train2017": [1, 2, 3], "val2017": [4, 5], "test2017": [6, 7]})


def _edit(root: Path, split: str, fn) -> None:
    p = root / "annotations" / f"instances_{split}.json"
    doc = json.loads(p.read_text())
    fn(doc)
    p.write_text(json.dumps(doc))


def test_clean_dataset_passes(coco):
    rep = validate(coco, CFG)
    assert rep.to_dict()["passed"], rep.to_dict()["errors"]
    assert rep.stats["train2017"]["class_counts"] == {"dent": 3, "scratch": 3}


def test_missing_image_fails(coco):
    (coco / "val2017" / "val2017_0.jpg").unlink()
    assert "image_file_missing" in validate(coco, CFG).errors


def test_truncated_image_fails(coco):
    path = coco / "train2017" / "train2017_1.jpg"
    path.write_bytes(path.read_bytes()[:200])
    assert "image_file_cannot" in validate(coco, CFG).errors


def test_size_mismatch_fails(coco):
    _photo(1).resize((40, 30)).save(coco / "train2017" / "train2017_0.jpg")
    assert "image_file_size" in validate(coco, CFG).errors


def test_missing_annotation_file_fails(coco):
    (coco / "annotations" / "instances_test2017.json").unlink()
    assert "annotation_file_missing" in validate(coco, CFG).errors


def test_bad_polygon_fails_above_tolerance(coco):
    _edit(coco, "train2017", lambda d: d["annotations"][0].update(segmentation=[[1, 2, 3]]))
    rep = validate(coco, CFG)
    assert "too_many_malformed_annotations" in rep.errors
    tolerant = validate(coco, {**CFG, "max_bad_annotation_frac": 0.5})
    assert tolerant.to_dict()["passed"] and "annotation_malformed" in tolerant.warnings


def test_unknown_category_and_class_mismatch_fail(coco):
    _edit(coco, "val2017", lambda d: d["annotations"][0].update(category_id=99))
    _edit(coco, "test2017", lambda d: d["categories"][0].update(name="dint"))
    errors = validate(coco, CFG).errors
    assert "annotation_unknown_category" in errors and "class_list_mismatch" in errors


def test_same_file_name_in_two_splits_fails(coco):
    _edit(coco, "val2017", lambda d: d["images"][0].update(file_name="train2017_0.jpg"))
    (coco / "val2017" / "val2017_0.jpg").rename(coco / "val2017" / "train2017_0.jpg")
    assert "file_name_in_two_splits" in validate(coco, CFG).errors


def test_leakage_drops_train_copy_of_a_test_photo(tmp_path):
    root = make_coco(tmp_path / "coco", {"train2017": [1, 2, 3], "val2017": [4, 5], "test2017": [6, 7]})
    # Re-encode test photo 7 darker into train: a near-duplicate, not a byte copy.
    darker = Image.eval(_photo(7), lambda v: int(v * 0.9))
    darker.save(root / "train2017" / "train2017_2.jpg", quality=70)

    splits = {s: load_split(root, f"{s}2017") for s in ("train", "val", "test")}
    found = find_leaks(splits, max_hamming=36)
    assert found["exclude"] == {"train": {"train2017_2.jpg"}, "val": set(), "test": set()}


def test_leakage_drops_val_copy_of_a_test_photo_and_keeps_test(tmp_path):
    root = make_coco(tmp_path / "coco", {"train2017": [1, 2, 3], "val2017": [4, 6], "test2017": [6, 7]})
    splits = {s: load_split(root, f"{s}2017") for s in ("train", "val", "test")}
    found = find_leaks(splits, max_hamming=36)
    assert found["exclude"]["val"] == {"val2017_1.jpg"} and not found["exclude"]["test"]
    assert any(p.get("identical") for p in found["pairs"])
