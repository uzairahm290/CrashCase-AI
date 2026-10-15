import pytest
from conftest import make_image, to_bytes
from fastapi.testclient import TestClient

pytest.importorskip("evidently")


def _post(c, img, category="sedan"):
    files = [("files", ("a.jpg", to_bytes(img), "image/jpeg"))]
    return c.post("/claims", files=files, data={"car_category": category}).json()


def test_drift_not_enough_data_then_detects_dark_photos(settings, monkeypatch):
    monkeypatch.setenv("CC_MIN_BLUR_SCORE", "0")
    monkeypatch.setenv("CC_MIN_BRIGHTNESS", "0")
    from crashcase.config import get_settings

    get_settings.cache_clear()
    from crashcase.api.main import app

    with TestClient(app) as c:
        assert c.get("/drift").json() is None
        _post(c, make_image(1))
        r = c.post("/drift/run").json()
        assert r["status"] == "not_enough_data"

        # Reference: normal daylight photos. Current: much darker photos.
        for i in range(30):
            _post(c, make_image(100 + i))
        for i in range(30):
            _post(c, make_image(200 + i, brightness=0.35))

        r = c.post("/drift/run").json()
        assert r["status"] in ("drift", "ok")
        assert "brightness" in r["drifted_columns"], r
        assert r["has_report"]
        html = c.get(f"/drift/{r['id']}/report", params={"part": "photos"})
        assert html.status_code == 200 and "<html" in html.text.lower()
        assert c.get("/drift").json()["id"] == r["id"]
