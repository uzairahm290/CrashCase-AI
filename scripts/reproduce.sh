#!/usr/bin/env bash
# Reproduce the registered model from a clean clone:
#   validate -> leakage check -> convert -> baselines -> train -> register, all logged to MLflow,
# then compare the new metrics with the ones committed in git.
#
#   bash scripts/reproduce.sh            # whole pipeline, forced, so every run lands in MLflow
#   bash scripts/reproduce.sh baseline   # stop after a given stage
set -euo pipefail
cd "$(dirname "$0")/.."
git config --global --add safe.directory "$PWD" 2>/dev/null || true  # repo mounted into a container

if [ ! -d datasets/CarDD_COCO ]; then
  echo "== fetching the raw dataset from the DVC remote"
  dvc pull datasets/CarDD_COCO.dvc || {
    echo "No DVC remote access. Request CarDD (https://cardd-ustc.github.io) and put CarDD_COCO in datasets/." >&2
    exit 1
  }
fi

echo "== MLflow: ${MLFLOW_TRACKING_URI:-sqlite:///mlflow.db (local)}"
dvc repro --force ${1:+"$1"}

echo "== metrics: this run vs the committed (registered) run"
dvc metrics diff HEAD --all || true
