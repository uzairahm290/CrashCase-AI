"""training/train.py registers every run but moves `champion` only on a val improvement."""

import pytest

mlflow = pytest.importorskip("mlflow")


def _train_helpers() -> dict:
    from pathlib import Path

    # promote_if_best and register from training/train.py, without importing ultralytics.
    src = (Path(__file__).parents[1] / "training" / "train.py").read_text()
    ns: dict = {"SELECT_METRIC": "metrics/mAP50-95_M"}
    exec(src[src.index("def promote_if_best(") : src.index("def main(")], ns)
    return ns


def _run_with(score):
    with mlflow.start_run() as run:
        mlflow.log_metric("metrics/mAP50-95_M", score)
        mlflow.log_text("weights", "weights/best.txt")
    return run


def test_training_moves_champion_only_on_improvement(tmp_path, monkeypatch):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_registry_uri(f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.chdir(tmp_path)
    h = _train_helpers()
    client = mlflow.MlflowClient()

    def train_and_register(score):
        mv = h["register"]("m", _run_with(score))
        return h["promote_if_best"]("m", mv.version, score)

    assert train_and_register(0.40)
    assert not train_and_register(0.35)  # worse: registered, but not champion
    assert train_and_register(0.45)
    assert str(client.get_model_version_by_alias("m", "champion").version) == "3"
    assert [v.version for v in client.search_model_versions("name='m'") if v.tags.get("champion")]


def test_champion_tag_fallback_without_alias_support(tmp_path, monkeypatch):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_registry_uri(f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.chdir(tmp_path)
    h = _train_helpers()

    def no_alias(*a, **k):
        raise mlflow.exceptions.MlflowException("aliases not supported")

    monkeypatch.setattr(mlflow.MlflowClient, "get_model_version_by_alias", no_alias)
    monkeypatch.setattr(mlflow.MlflowClient, "set_registered_model_alias", no_alias)
    v1 = h["register"]("m", _run_with(0.40)).version
    assert h["promote_if_best"]("m", v1, 0.40)
    v2 = h["register"]("m", _run_with(0.30)).version
    assert not h["promote_if_best"]("m", v2, 0.30)  # compared against the tagged champion
