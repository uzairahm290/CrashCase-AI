from conftest import make_image, to_bytes
from fastapi.testclient import TestClient


def _client():
    from crashcase.api.main import app

    return TestClient(app)


def _files(*images):
    return [("files", (f"img{i}.jpg", to_bytes(img), "image/jpeg")) for i, img in enumerate(images)]


def test_health(settings):
    with _client() as c:
        r = c.get("/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"
        assert c.get("/metrics").status_code == 200


def test_full_claim_flow(settings):
    with _client() as c:
        r = c.post("/claims", files=_files(make_image(10), make_image(11)), data={"car_category": "sedan"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "done", body
        result = body["result"]
        assert len(result["assessments"]) == 2
        a = result["assessments"][0]
        assert a["basis"] == "retrieval" and len(a["similar_claims"]) == 5
        assert a["cost_low_pkr"] <= a["cost_estimate_pkr"] <= a["cost_high_pkr"]
        assert result["total_low_pkr"] < result["total_high_pkr"]
        assert "PC-" in result["report"] and result["model_versions"]["report"] == "template"
        assert not result["fraud"]["flagged"]

        claim_id = body["claim_id"]
        assert c.get(f"/claims/{claim_id}").json()["status"] == "done"

        # Same photo again in a new claim -> duplicate-photo fraud flag
        r2 = c.post("/claims", files=_files(make_image(10)), data={"car_category": "sedan"})
        fraud = r2.json()["result"]["fraud"]
        assert fraud["flagged"] and claim_id in fraud["reasons"][0]


def test_review_feeds_index(settings):
    from crashcase.pipeline.run import get_pipeline

    with _client() as c:
        claim = c.post("/claims", files=_files(make_image(20)), data={"car_category": "suv"}).json()
        before = get_pipeline().index.count()
        r = c.post(f"/claims/{claim['claim_id']}/review", json={"approved": True, "final_cost_pkr": 50000})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert get_pipeline().index.count() == before + 1
        # Can't review twice
        assert c.post(f"/claims/{claim['claim_id']}/review", json={"approved": True}).status_code == 409


def test_rejected_when_all_photos_bad(settings):
    with _client() as c:
        r = c.post("/claims", files=_files(make_image(blur=True)), data={"car_category": "sedan"})
        body = r.json()
        assert body["status"] == "rejected"
        assert body["result"]["assessments"] == []


def test_validation(settings):
    with _client() as c:
        assert (
            c.post("/claims", files=_files(make_image()), data={"car_category": "truck"}).status_code == 422
        )
        bad = [("files", ("x.jpg", b"not an image", "image/jpeg"))]
        assert c.post("/claims", files=bad, data={"car_category": "sedan"}).status_code == 422
        assert c.get("/claims/nope").status_code == 404
