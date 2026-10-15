import pytest

pytest.importorskip("prefect")


def test_reindex_reembeds_after_embedder_change(settings):
    from conftest import make_image, to_bytes
    from fastapi.testclient import TestClient

    from crashcase.api.main import app
    from crashcase.maintenance import reindex
    from crashcase.pipeline.run import get_pipeline

    with TestClient(app) as c:
        files = [("files", ("a.jpg", to_bytes(make_image(7)), "image/jpeg"))]
        cid = c.post("/claims", files=files, data={"car_category": "sedan"}).json()["claim_id"]
        c.post(f"/claims/{cid}/review", json={"approved": True})

    pipe = get_pipeline()
    total = pipe.index.count()
    assert reindex(pipe)["stale"] == 0  # nothing to do on the same embedder

    pipe.embedder.version = "rgb-hist-v2"  # pretend the embedding model changed
    out = reindex(pipe, per_group=20)
    assert out["reembedded"] == 1 and out["regenerated"] == total - 1 and out["skipped"] == 0
    assert pipe.index.count() == total
    assert pipe.index.stale("rgb-hist-v2") == [] or all(
        c.embedder_version == "synthetic:rgb-hist-v2" for c in pipe.index.stale("rgb-hist-v2")
    )


def test_drift_flow_runs(settings):
    from prefect.testing.utilities import prefect_test_harness

    from crashcase.flows.drift_flow import drift_check

    with prefect_test_harness():
        assert drift_check(current_days=7)["status"] == "not_enough_data"
