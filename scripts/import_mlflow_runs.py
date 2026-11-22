"""Copy runs and registered models from a local MLflow store into another tracking server.

Kaggle notebooks can't always reach the team's MLflow, so the pipeline logs to a local
mlflow.db there. This replays that store into the real server, unchanged:

    MLFLOW_TRACKING_URI=https://dagshub.com/<user>/<repo>.mlflow \\
    MLFLOW_TRACKING_USERNAME=<user> MLFLOW_TRACKING_PASSWORD=<token> \\
    python scripts/import_mlflow_runs.py --src-db kaggle/mlflow.db --src-artifacts kaggle/mlruns

Each run keeps its name, params, metrics (with their original timestamps and steps), tags, start
and end time, and artifacts. It is tagged `imported_from` with its original run id. Registered
model versions are re-created against the copied runs, with their tags and aliases.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mlflow import MlflowClient
from mlflow.entities import Metric, Param
from mlflow.exceptions import MlflowException


def copy_artifacts(src: MlflowClient, dst: MlflowClient, src_run, dst_run_id: str, root: Path, prefix: str):
    base = Path(src_run.info.artifact_uri.removeprefix("file://").replace(prefix, str(root), 1))
    if base.exists():
        for child in sorted(base.iterdir()):
            if child.is_dir():
                dst.log_artifacts(dst_run_id, str(child), artifact_path=child.name)
            else:
                dst.log_artifact(dst_run_id, str(child))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--src-db", required=True)
    p.add_argument("--src-artifacts", required=True, help="the source mlruns/ directory")
    p.add_argument("--src-prefix", default="/tmp/CrashCase-AI/mlruns", help="artifact root as recorded")
    p.add_argument("--source-label", default="kaggle")
    args = p.parse_args()

    src = MlflowClient(tracking_uri=f"sqlite:///{Path(args.src_db).resolve()}")
    dst = MlflowClient()
    root = Path(args.src_artifacts).resolve()
    run_map: dict[str, str] = {}

    for exp in src.search_experiments():
        runs = src.search_runs([exp.experiment_id], order_by=["attributes.start_time ASC"])
        if not runs:
            continue
        found = dst.get_experiment_by_name(exp.name)
        exp_id = found.experiment_id if found else dst.create_experiment(exp.name)
        for r in runs:
            tags = {
                k: v for k, v in r.data.tags.items() if not k.startswith("mlflow.") or k == "mlflow.runName"
            }
            tags |= {"imported_from": f"{args.source_label}:{r.info.run_id}"}
            new = dst.create_run(exp_id, start_time=r.info.start_time, tags=tags, run_name=r.info.run_name)
            metrics = [
                Metric(m.key, m.value, m.timestamp, m.step)
                for key in r.data.metrics
                for m in src.get_metric_history(r.info.run_id, key)
            ]
            params = [Param(k, v) for k, v in r.data.params.items()]
            for i in range(0, max(len(metrics), len(params), 1), 100):  # server batch limits
                dst.log_batch(new.info.run_id, metrics=metrics[i : i + 100], params=params[i : i + 100])
            copy_artifacts(src, dst, r, new.info.run_id, root, args.src_prefix)
            dst.set_terminated(new.info.run_id, status=r.info.status, end_time=r.info.end_time)
            run_map[r.info.run_id] = new.info.run_id
            print(f"run {r.info.run_name}: {r.info.run_id} -> {new.info.run_id}")

    for model in src.search_registered_models():
        try:
            dst.create_registered_model(model.name)
        except MlflowException:
            pass  # already exists
        versions = sorted(src.search_model_versions(f"name='{model.name}'"), key=lambda v: int(v.version))
        for v in versions:
            new_run = run_map[v.run_id]
            mv = dst.create_model_version(
                model.name, source=f"{dst.get_run(new_run).info.artifact_uri}/weights", run_id=new_run
            )
            origin = f"{args.source_label}:{model.name}/{v.version}"
            for k, val in {**v.tags, "imported_from": origin}.items():
                dst.set_model_version_tag(model.name, mv.version, k, val)
            for alias in (a for a, ver in model.aliases.items() if str(ver) == str(v.version)):
                try:
                    dst.set_registered_model_alias(model.name, alias, mv.version)
                except MlflowException as e:
                    print(f"alias {alias} not set ({e}); version is tagged instead")
            print(f"model {model.name} v{v.version} -> v{mv.version}")


if __name__ == "__main__":
    main()
