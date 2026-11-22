"""Pieces shared by baseline.py and train.py: dataset versioning and the image-level metric.

Image-level task: for each photo, which damage types are present (multi-label, 6 classes)?
A classical model can't produce masks, so this is where the baseline and YOLO are compared
on equal terms. YOLO's own mask/box mAP is logged next to it.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import numpy as np
import yaml

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def data_yaml(path: str | Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text())
    cfg["root"] = Path(cfg["path"])
    return cfg


def split_images(cfg: dict, split: str) -> list[Path]:
    return sorted(p for p in (cfg["root"] / cfg[split]).iterdir() if p.suffix.lower() in IMAGE_EXTS)


def label_path(image: Path) -> Path:
    # Ultralytics layout: .../images/<split>/x.jpg -> .../labels/<split>/x.txt
    parts = list(image.parts)
    parts[len(parts) - 1 - parts[::-1].index("images")] = "labels"
    return Path(*parts).with_suffix(".txt")


def image_labels(images: list[Path], n_classes: int) -> np.ndarray:
    """(n_images, n_classes) 0/1 matrix: which classes have at least one polygon in the image."""
    y = np.zeros((len(images), n_classes), dtype=np.int8)
    for i, im in enumerate(images):
        lp = label_path(im)
        if lp.exists():
            for line in lp.read_text().splitlines():
                if line.strip():
                    y[i, int(line.split()[0])] = 1
    return y


def multilabel_metrics(y_true: np.ndarray, y_pred: np.ndarray, names: list[str], prefix: str) -> dict:
    """Per-class and macro/micro F1, plus exact-match accuracy, keyed for MLflow."""
    out = {}
    f1s = []
    tp_all = fp_all = fn_all = 0
    for c, name in enumerate(names):
        t, p = y_true[:, c].astype(bool), y_pred[:, c].astype(bool)
        tp, fp, fn = int((t & p).sum()), int((~t & p).sum()), int((t & ~p).sum())
        tp_all, fp_all, fn_all = tp_all + tp, fp_all + fp, fn_all + fn
        f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
        f1s.append(f1)
        out[f"{prefix}/f1_{name}"] = f1
    out[f"{prefix}/macro_f1"] = float(np.mean(f1s))
    denom = 2 * tp_all + fp_all + fn_all
    out[f"{prefix}/micro_f1"] = 2 * tp_all / denom if denom else 0.0
    out[f"{prefix}/exact_match"] = float((y_true == y_pred).all(axis=1).mean())
    return out


def dvc_hashes(lock: str | Path = "dvc.lock") -> dict[str, str]:
    """md5 that DVC recorded for each dataset directory: the version a run was trained on."""
    lock = Path(lock)
    if not lock.exists():
        return {}
    found = {}
    for stage in (yaml.safe_load(lock.read_text()) or {}).get("stages", {}).values():
        for entry in stage.get("deps", []) + stage.get("outs", []):
            if entry["path"].startswith("datasets/") and "md5" in entry:
                found[entry["path"]] = entry["md5"]
    return found


def fingerprint(root: Path) -> str:
    """Content hash of every label file plus every image's name and size.

    Same answer wherever the data lives (local, Docker, Kaggle), with or without DVC, and far
    cheaper than hashing 3 GB of JPEGs. Any changed label, added or removed image changes it.
    """
    h = hashlib.md5()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in {".txt", *IMAGE_EXTS}:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes() if p.suffix == ".txt" else str(p.stat().st_size).encode())
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def version_tags(cfg: dict) -> dict[str, str]:
    """MLflow tags that pin a run to the exact code and data it used."""
    tags = {"git_commit": git_commit(), "data_fingerprint": fingerprint(cfg["root"])}
    for path, md5 in dvc_hashes().items():
        tags[f"dvc_md5/{path}"] = md5
    return tags
