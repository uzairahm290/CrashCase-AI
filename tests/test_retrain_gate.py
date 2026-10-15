import pytest

mlflow = pytest.importorskip("mlflow")
pytest.importorskip("prefect")


def _register(score):
    from pathlib import Path

    # Use the same registration helper as training/train.py (without importing ultralytics).
    src = (Path(__file__).parents[1] / "training" / "train.py").read_text()
    helper = src[src.index("def register(") : src.index("def main(")]
    ns: dict = {}
    exec(helper, ns)
    with mlflow.start_run() as run:
        mlflow.log_metric("metrics/mAP50-95_M", score)
        mlflow.log_text("weights", "weights/best.txt")
    return ns["register"]("crashcase-damage-seg", run).version


def test_gate_promotes_only_non_regressing_models(tmp_path, monkeypatch):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_registry_uri(f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.chdir(tmp_path)
    from crashcase.flows.retrain_flow import gate

    _register(0.40)
    first = gate.fn(tolerance=0.01)  # .fn = the plain function, no Prefect server needed
    assert first["promoted"] and first["champion_score"] is None

    _register(0.30)  # clearly worse -> stays out
    worse = gate.fn(tolerance=0.01)
    assert not worse["promoted"] and worse["champion_score"] == pytest.approx(0.40)

    _register(0.395)  # within tolerance -> promoted
    assert gate.fn(tolerance=0.01)["promoted"]

    champ = mlflow.MlflowClient().get_model_version_by_alias("crashcase-damage-seg", "champion")
    assert str(champ.version) == "3"  # int on MLflow 3, str on MLflow 2


def test_detector_resolves_champion_weights(tmp_path, monkeypatch):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_registry_uri(f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.chdir(tmp_path)
    from crashcase.pipeline.detector import resolve_weights

    (tmp_path / "best.pt").write_bytes(b"fake weights")
    with mlflow.start_run() as run:
        mlflow.log_artifact(str(tmp_path / "best.pt"), artifact_path="weights")
    client = mlflow.MlflowClient()
    client.create_registered_model("m")
    v = client.create_model_version("m", f"{run.info.artifact_uri}/weights", run.info.run_id)
    client.set_registered_model_alias("m", "champion", v.version)

    path = resolve_weights("models:/m@champion")
    assert path.endswith("best.pt") and open(path, "rb").read() == b"fake weights"
    assert resolve_weights("models/local.pt") == "models/local.pt"
