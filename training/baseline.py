"""Two baselines, logged to MLflow before the main model is trained.

    python training/baseline.py        # reads params.yaml -> baseline, data from train.data

1. prior: a rule. Predict a damage type for every photo if it appears in at least half of the
   training photos. Anything that can't beat this has learned nothing.
2. hog-logreg: classical vision. Colour histograms (HSV) and gradient-orientation histograms on a
   2x2 grid of a small thumbnail, then one logistic regression per damage type. The decision
   threshold for each type is tuned on val, never on test.

Both are scored on the image-level task in common.py, on val and on the held-out test split,
so they line up against YOLO's image-level numbers in the same MLflow experiment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import mlflow
import numpy as np
import yaml
from common import data_yaml, image_labels, multilabel_metrics, split_images, version_tags
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

OUT = Path("reports/baseline_metrics.json")


def features(path: Path, thumb: int) -> np.ndarray:
    with Image.open(path) as im:
        im.draft("RGB", (thumb * 4, thumb * 4))
        rgb = im.convert("RGB").resize((thumb, thumb))
    hsv = np.asarray(rgb.convert("HSV"), dtype=np.float32) / 255.0
    gray = np.asarray(rgb.convert("L"), dtype=np.float32) / 255.0

    feats = [np.histogram(hsv[..., c], bins=16, range=(0, 1))[0] / gray.size for c in range(3)]
    gy, gx = np.gradient(gray)
    mag = np.hypot(gx, gy)
    ang = np.mod(np.arctan2(gy, gx), np.pi)  # unsigned orientation
    half = thumb // 2
    for r in (slice(0, half), slice(half, None)):
        for c in (slice(0, half), slice(half, None)):
            h, _ = np.histogram(ang[r, c], bins=9, range=(0, np.pi), weights=mag[r, c])
            feats.append(h / (h.sum() + 1e-6))
            feats.append([gray[r, c].mean(), gray[r, c].std(), (mag[r, c] > 0.1).mean()])
    return np.concatenate([np.ravel(f) for f in feats]).astype(np.float32)


def tune_thresholds(y: np.ndarray, proba: np.ndarray) -> np.ndarray:
    """Per class, the probability cut-off that maximises F1 on the given (val) split."""
    grid = np.linspace(0.05, 0.95, 19)
    best = np.full(y.shape[1], 0.5)
    for c in range(y.shape[1]):
        scores = []
        for t in grid:
            p = proba[:, c] >= t
            tp, fp, fn = (p & (y[:, c] == 1)).sum(), (p & (y[:, c] == 0)).sum(), (~p & (y[:, c] == 1)).sum()
            scores.append(2 * tp / max(2 * tp + fp + fn, 1))
        best[c] = grid[int(np.argmax(scores))]
    return best


def log_run(name: str, params: dict, tags: dict, metrics: dict, extra: dict) -> None:
    with mlflow.start_run(run_name=name):
        mlflow.set_tags({**tags, "model_type": "baseline", "stage": "baseline"})
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_dict(extra, "baseline_details.json")
        mlflow.log_artifact("params.yaml")
        if Path("dvc.lock").exists():
            mlflow.log_artifact("dvc.lock")


def main() -> None:
    all_params = yaml.safe_load(Path("params.yaml").read_text())
    params = all_params["baseline"]
    cfg = data_yaml(all_params["train"]["data"])
    names = [cfg["names"][i] for i in sorted(cfg["names"])]
    rng_seed = params["seed"]

    imgs = {s: split_images(cfg, s) for s in ("train", "val", "test")}
    y = {s: image_labels(v, len(names)) for s, v in imgs.items()}
    tags = version_tags(cfg)
    split_sizes = {f"n_{s}": len(v) for s, v in imgs.items()}

    os.environ.setdefault("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    mlflow.set_experiment(params["experiment"])
    results = {}

    # 1. prior rule
    prevalence = y["train"].mean(axis=0)
    rule = (prevalence >= 0.5).astype(np.int8)
    m = {}
    for s in ("val", "test"):
        m |= multilabel_metrics(y[s], np.tile(rule, (len(y[s]), 1)), names, s)
    log_run(
        "baseline-prior",
        {"rule": "predict class if train prevalence >= 0.5", **split_sizes},
        tags,
        m,
        {"train_prevalence": dict(zip(names, prevalence.round(4).tolist(), strict=True))},
    )
    results["prior"] = m
    print(f"prior:      val macro F1 {m['val/macro_f1']:.3f}  test macro F1 {m['test/macro_f1']:.3f}")

    # 2. hand-crafted features + logistic regression
    x = {s: np.stack([features(p, params["thumb"]) for p in v]) for s, v in imgs.items()}
    clf = make_pipeline(
        StandardScaler(),
        OneVsRestClassifier(
            LogisticRegression(C=params["C"], class_weight="balanced", max_iter=2000, random_state=rng_seed)
        ),
    )
    clf.fit(x["train"], y["train"])
    thresholds = tune_thresholds(y["val"], clf.predict_proba(x["val"]))
    m = {}
    for s in ("val", "test"):
        pred = (clf.predict_proba(x[s]) >= thresholds).astype(np.int8)
        m |= multilabel_metrics(y[s], pred, names, s)
    log_run(
        "baseline-hog-logreg",
        {
            "features": "HSV hist 3x16 + 2x2 grid of (9-bin gradient hist, mean, std, edge density)",
            "n_features": x["train"].shape[1],
            "classifier": "one-vs-rest logistic regression, class_weight=balanced",
            "thresholds": "tuned per class on val",
            **{k: v for k, v in params.items() if k != "experiment"},
            **split_sizes,
        },
        tags,
        m,
        {"thresholds": dict(zip(names, thresholds.round(2).tolist(), strict=True))},
    )
    results["hog_logreg"] = m
    print(f"hog-logreg: val macro F1 {m['val/macro_f1']:.3f}  test macro F1 {m['test/macro_f1']:.3f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    rounded = {k: {n: round(v, 4) for n, v in r.items()} for k, r in results.items()}
    OUT.write_text(json.dumps(rounded, indent=2))


if __name__ == "__main__":
    main()
