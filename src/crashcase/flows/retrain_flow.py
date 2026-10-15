"""Retrain the damage model, and promote it only if it beats the current champion.

    labels -> dvc pull -> train (logs to MLflow) -> evaluate gate -> alias "champion"
           -> (optional) trigger the GitHub deploy workflow

Workers load `models:/crashcase-damage-seg@champion` when CC_DAMAGE_WEIGHTS points there,
so promotion plus a deploy rolls the new model out through the canary.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx
from prefect import flow, get_run_logger, task

MODEL = os.getenv("CC_REGISTERED_MODEL", "crashcase-damage-seg")
GATE_METRIC = "metrics/mAP50-95_M"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(cmd: list[str]) -> None:
    get_run_logger().info("$ %s", " ".join(cmd))
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


@task
def pull_data() -> None:
    if (REPO_ROOT / "dvc.yaml").exists() and subprocess.run(
        ["which", "dvc"], capture_output=True
    ).returncode == 0:
        _run(["dvc", "pull"])
    else:
        get_run_logger().warning("dvc not available; training on the data already on disk")


@task
def train() -> dict:
    _run(["python", "training/train.py"])
    return json.loads((REPO_ROOT / "metrics.json").read_text())


@task
def gate(tolerance: float) -> dict:
    """Champion = best so far. A new version must not be worse by more than `tolerance`."""
    from mlflow import MlflowClient

    client = MlflowClient()
    latest = max(client.search_model_versions(f"name='{MODEL}'"), key=lambda v: int(v.version))
    new_score = client.get_run(latest.run_id).data.metrics.get(GATE_METRIC, 0.0)
    try:
        champ = client.get_model_version_by_alias(MODEL, "champion")
        champ_score = client.get_run(champ.run_id).data.metrics.get(GATE_METRIC, 0.0)
    except Exception:
        champ, champ_score = None, None

    promote = champ is None or new_score >= champ_score - tolerance
    if promote:
        client.set_registered_model_alias(MODEL, "champion", latest.version)
    client.set_model_version_tag(MODEL, latest.version, "gate", "passed" if promote else "failed")
    return {
        "version": latest.version,
        "score": new_score,
        "champion_score": champ_score,
        "promoted": promote,
    }


@task
def trigger_deploy(reason: str) -> None:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO", "uzairahm290/crashcase-ai")
    if not token:
        get_run_logger().info("GITHUB_TOKEN not set; deploy the new model from the Actions tab")
        return
    r = httpx.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/deploy.yml/dispatches",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"canary_percent": "10", "bake_seconds": "600"}},
        timeout=30,
    )
    r.raise_for_status()
    get_run_logger().info("deploy triggered: %s", reason)


@flow(name="retrain-damage-model")
def retrain(reason: str = "manual", tolerance: float = 0.01, deploy: bool = True) -> dict:
    log = get_run_logger()
    log.info("retraining because: %s", reason)
    pull_data()
    metrics = train()
    decision = gate(tolerance)
    log.info("gate: %s (val metrics %s)", decision, {k: round(v, 4) for k, v in metrics.items()})
    if decision["promoted"] and deploy:
        trigger_deploy(f"model v{decision['version']} promoted ({reason})")
    return decision
