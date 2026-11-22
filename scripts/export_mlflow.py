"""Export MLflow runs and the model registry to plain files, for submission and review.

    python scripts/export_mlflow.py --out docs/mlflow
    MLFLOW_TRACKING_URI=http://localhost:5000 python scripts/export_mlflow.py

Writes:
    runs.csv              one row per run: name, type, params, key metrics, data/code versions
    runs.json             everything MLflow holds for each run (params, metrics, tags)
    registered_model.json every version of the registered model, its tags and aliases
    comparison.md         baselines vs YOLO on the held-out test split
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import mlflow
from mlflow import MlflowClient

KEY_METRICS = [
    "test/macro_f1",
    "test/micro_f1",
    "test/exact_match",
    "val/macro_f1",
    "test/mAP50-95_M",
    "test/mAP50_M",
    "metrics/mAP50-95_M",
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/mlflow")
    p.add_argument("--experiment", default="crashcase-damage-seg")
    p.add_argument("--model", default="crashcase-damage-seg")
    args = p.parse_args()
    os.environ.setdefault("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    runs = mlflow.search_runs(experiment_names=[args.experiment], order_by=["start_time ASC"])
    if runs.empty:
        raise SystemExit(f"no runs in experiment {args.experiment!r} at {mlflow.get_tracking_uri()}")
    keep = ["run_id", "tags.mlflow.runName", "tags.model_type", "status", "start_time"]
    keep += [c for c in runs.columns if c.startswith(("params.", "tags.git_commit", "tags.data_fingerprint"))]
    keep += [f"metrics.{m}" for m in KEY_METRICS if f"metrics.{m}" in runs.columns]
    runs[keep].to_csv(out / "runs.csv", index=False)

    client = MlflowClient()
    full = []
    for run_id in runs["run_id"]:
        r = client.get_run(run_id)
        full.append(
            {
                "run_id": run_id,
                "name": r.info.run_name,
                "status": r.info.status,
                "start_time": r.info.start_time,
                "params": r.data.params,
                "metrics": r.data.metrics,
                "tags": {k: v for k, v in r.data.tags.items() if not k.startswith("mlflow.log-model")},
                "artifact_uri": r.info.artifact_uri,
            }
        )
    (out / "runs.json").write_text(json.dumps(full, indent=2, default=str))

    versions = sorted(client.search_model_versions(f"name='{args.model}'"), key=lambda v: int(v.version))
    model = client.get_registered_model(args.model) if versions else None
    (out / "registered_model.json").write_text(
        json.dumps(
            {
                "name": args.model,
                "aliases": dict(model.aliases) if model else {},
                "versions": [
                    {
                        "version": v.version,
                        "run_id": v.run_id,
                        "source": v.source,
                        "status": v.status,
                        "created": v.creation_timestamp,
                        "tags": dict(v.tags),
                        "aliases": list(v.aliases),
                    }
                    for v in versions
                ],
            },
            indent=2,
            default=str,
        )
    )

    rows = [
        "| Run | Type | test macro F1 | test micro F1 | test exact match | test mask mAP50-95 |",
        "|---|---|---|---|---|---|",
    ]
    for r in full:
        m = r["metrics"]

        def f(k, m=m):
            return f"{m[k]:.3f}" if k in m else "n/a"

        rows.append(
            f"| {r['name']} | {r['tags'].get('model_type', '')} | {f('test/macro_f1')} "
            f"| {f('test/micro_f1')} | {f('test/exact_match')} | {f('test/mAP50-95_M')} |"
        )
    (out / "comparison.md").write_text(
        "Image-level damage-type detection on the held-out CarDD test split.\n\n" + "\n".join(rows) + "\n"
    )
    print(f"exported {len(full)} runs and {len(versions)} model versions to {out}")


if __name__ == "__main__":
    main()
