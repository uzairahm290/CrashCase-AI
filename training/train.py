"""Fine-tune YOLOv8-seg and track everything in MLflow.

    python training/train.py            # reads params.yaml; normally run by `dvc repro`

MLFLOW_TRACKING_URI picks the server (the compose stack's is http://localhost:5000); unset, runs
go to ./mlflow.db, which `mlflow ui --backend-store-uri sqlite:///mlflow.db` opens.

What the run records:
  params     everything under `train:` in params.yaml, and the split sizes
  tags       git commit, DVC md5 of the raw and converted data, a content fingerprint of the data
  metrics    val/...    mask and box mAP on val (used for early stopping and model selection)
             test/...   the same on the held-out test split, plus the image-level F1 that the
                        baselines report, so the two can be compared directly
  artifacts  best weights, training plots, params.yaml, dvc.lock, the leakage report

The run's weights are registered as a new version of `train.registered_model`. The `champion`
alias moves to it only if its val mask mAP beats the current champion's. Test scores never pick
the model: they are reported, not optimised.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import mlflow
import numpy as np
import yaml
from common import data_yaml, image_labels, multilabel_metrics, split_images, version_tags
from ultralytics import YOLO
from ultralytics import settings as yolo_settings

SELECT_METRIC = "metrics/mAP50-95_M"  # val mask mAP; the retrain flow's gate reads the same key


def clean(key: str) -> str:
    # "metrics/mAP50-95(M)" -> "metrics/mAP50-95_M"; MLflow rejects parentheses
    return re.sub(r"[^\w\-./ ]", "_", key).strip("_")


def evaluate(weights: Path, data: str, split: str, imgsz: int, batch: int) -> dict:
    res = YOLO(weights).val(
        data=data, split=split, imgsz=imgsz, batch=batch, project="runs", name=f"eval-{split}", exist_ok=True
    )
    return {clean(k): float(v) for k, v in res.results_dict.items()}


def image_level(weights: Path, cfg: dict, split: str, names: list[str], conf: float, imgsz: int) -> dict:
    model = YOLO(weights)
    images = split_images(cfg, split)
    y_true = image_labels(images, len(names))
    y_pred = np.zeros_like(y_true)
    for start in range(0, len(images), 32):
        batch = [str(p) for p in images[start : start + 32]]
        for i, r in enumerate(model.predict(batch, conf=conf, imgsz=imgsz, verbose=False)):
            for c in r.boxes.cls.int().tolist():
                y_pred[start + i, c] = 1
    return multilabel_metrics(y_true, y_pred, names, split)


def promote_if_best(name: str, version, score: float) -> bool:
    """Point the `champion` alias at this version if it beats the current champion on val."""
    from mlflow import MlflowClient

    client = MlflowClient()
    best = float("-inf")
    try:
        champ = client.get_model_version_by_alias(name, "champion")
        best = client.get_run(champ.run_id).data.metrics.get(SELECT_METRIC, best)
    except Exception:  # noqa: BLE001 - no champion yet, or a server without alias support
        tagged = [v for v in client.search_model_versions(f"name='{name}'") if v.tags.get("champion")]
        if tagged:
            best = max(client.get_run(v.run_id).data.metrics.get(SELECT_METRIC, best) for v in tagged)
    if score <= best:
        return False
    client.set_model_version_tag(name, version, "champion", "true")  # visible on any MLflow server
    try:
        client.set_registered_model_alias(name, "champion", version)
    except Exception as e:  # noqa: BLE001 - hosted servers on older MLflow lack aliases
        print(f"could not set the champion alias ({e}); the version is tagged champion=true")
    return True


def register(name: str, run):
    """Register the run's weights folder. Works on MLflow 2 and 3 (3 rejects register_model on
    plain artifacts, but create_model_version with an explicit source is fine on both)."""
    from mlflow import MlflowClient
    from mlflow.exceptions import MlflowException

    client = MlflowClient()
    try:
        client.create_registered_model(name)
    except MlflowException:
        pass  # already exists
    return client.create_model_version(
        name=name, source=f"{run.info.artifact_uri}/weights", run_id=run.info.run_id
    )


def main() -> None:
    params = yaml.safe_load(Path("params.yaml").read_text())["train"]
    cfg = data_yaml(params["data"])
    names = [cfg["names"][i] for i in sorted(cfg["names"])]
    yolo_settings.update({"mlflow": False})  # we log explicitly below

    os.environ.setdefault("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    mlflow.set_experiment(params.get("experiment", "crashcase-damage-seg"))
    with mlflow.start_run(run_name=params.get("run_name")) as run:
        mlflow.log_params(params)
        mlflow.log_params({f"n_{s}": len(split_images(cfg, s)) for s in ("train", "val", "test")})
        tags = version_tags(cfg)
        mlflow.set_tags({**tags, "model_type": "yolov8-seg", "stage": "train"})
        for f in ("params.yaml", "dvc.lock", "reports/leakage.json", "reports/data_validation.json"):
            if os.path.exists(f):
                mlflow.log_artifact(f, artifact_path="provenance")

        model = YOLO(params["model"])
        model.train(
            data=params["data"],
            epochs=params["epochs"],
            imgsz=params["imgsz"],
            batch=params["batch"],
            seed=params.get("seed", 0),
            deterministic=True,
            fraction=params.get("fraction", 1.0),
            project="runs",
            name="damage-seg",
            exist_ok=True,
        )
        # Ask the trainer where it saved: Ultralytics 8.4 nests runs under the task name
        run_dir = Path(model.trainer.save_dir)
        best = run_dir / "weights" / "best.pt"

        val = evaluate(best, params["data"], "val", params["imgsz"], params["batch"])
        test = evaluate(best, params["data"], "test", params["imgsz"], params["batch"])
        metrics = {
            **val,  # unprefixed "metrics/..." keys = val, kept for the retrain gate
            **{f"test/{k.removeprefix('metrics/')}": v for k, v in test.items() if k.startswith("metrics/")},
            **image_level(best, cfg, "val", names, params["conf"], params["imgsz"]),
            **image_level(best, cfg, "test", names, params["conf"], params["imgsz"]),
        }
        mlflow.log_metrics(metrics)

        Path("models").mkdir(exist_ok=True)
        shutil.copy2(best, "models/damage-seg.pt")
        mlflow.log_artifact(str(best), artifact_path="weights")
        for plot in run_dir.glob("*.png"):
            mlflow.log_artifact(str(plot), artifact_path="plots")

        mv = register(params["registered_model"], run)
        from mlflow import MlflowClient

        client = MlflowClient()
        for k in (SELECT_METRIC, "test/mAP50-95_M", "test/macro_f1"):
            client.set_model_version_tag(mv.name, mv.version, k, f"{metrics.get(k, float('nan')):.4f}")
        client.set_model_version_tag(mv.name, mv.version, "data_fingerprint", tags["data_fingerprint"])
        champion = promote_if_best(mv.name, mv.version, metrics[SELECT_METRIC])
        mlflow.set_tag("champion", str(champion).lower())
        print(f"registered {mv.name} version {mv.version}" + (" -> champion" if champion else ""))

        Path("metrics.json").write_text(json.dumps(metrics, indent=2))  # for `dvc metrics show`


if __name__ == "__main__":
    main()
