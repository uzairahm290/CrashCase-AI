"""Fine-tune YOLOv8-seg and track everything in MLflow.

    export MLFLOW_TRACKING_URI=http://localhost:5000   # or your hosted MLflow
    python training/train.py                            # reads params.yaml (DVC-tracked)

On Kaggle/Colab: pip install ultralytics mlflow, upload datasets/cardd_yolo, point
MLFLOW_TRACKING_URI at your MLflow server (or leave it unset to log to ./mlruns and sync later).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import mlflow
import yaml
from ultralytics import YOLO
from ultralytics import settings as yolo_settings


def clean(key: str) -> str:
    # "metrics/mAP50-95(M)" -> "metrics/mAP50-95_M"; MLflow rejects parentheses
    return re.sub(r"[^\w\-./ ]", "_", key).strip("_")


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
    yolo_settings.update({"mlflow": False})  # we log explicitly below

    mlflow.set_experiment(params.get("experiment", "crashcase-damage-seg"))
    with mlflow.start_run(run_name=params.get("run_name")) as run:
        mlflow.log_params(params)
        mlflow.set_tag("dataset", params["data"])
        if os.path.exists("dvc.lock"):
            mlflow.log_artifact("dvc.lock")  # ties this run to the exact data version

        model = YOLO(params["model"])
        model.train(
            data=params["data"],
            epochs=params["epochs"],
            imgsz=params["imgsz"],
            batch=params["batch"],
            seed=params.get("seed", 0),
            project="runs",
            name="damage-seg",
            exist_ok=True,
        )
        metrics = model.val(data=params["data"], split="val").results_dict
        metrics = {clean(k): float(v) for k, v in metrics.items()}
        mlflow.log_metrics(metrics)

        best = Path("runs/damage-seg/weights/best.pt")
        Path("models").mkdir(exist_ok=True)
        shutil.copy2(best, "models/damage-seg.pt")
        mlflow.log_artifact(str(best), artifact_path="weights")
        for plot in Path("runs/damage-seg").glob("*.png"):
            mlflow.log_artifact(str(plot), artifact_path="plots")

        # Register so the retrain flow's gate can promote it to the "champion" alias.
        mv = register(params["registered_model"], run)
        print(f"registered {params['registered_model']} version {mv.version}")

        Path("metrics.json").write_text(json.dumps(metrics, indent=2))  # for `dvc metrics show`


if __name__ == "__main__":
    main()
