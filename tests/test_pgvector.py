"""Integration test against a real Postgres + pgvector. Skipped unless CC_TEST_PG_URL is set.

CC_TEST_PG_URL=postgresql+psycopg2://user:pass@localhost:5432/crashcase pytest tests/test_pgvector.py
"""

import os

import pytest
from conftest import make_image, to_bytes
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

PG_URL = os.getenv("CC_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="CC_TEST_PG_URL not set")


@pytest.fixture
def pg_settings(settings, monkeypatch):
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS past_claims, image_hashes, claims"))
    engine.dispose()

    from crashcase import db
    from crashcase.config import get_settings
    from crashcase.pipeline.run import get_pipeline

    monkeypatch.setenv("CC_DATABASE_URL", PG_URL)
    monkeypatch.setenv("CC_INDEX_BACKEND", "pgvector")
    db._engines.clear()
    get_settings.cache_clear()
    get_pipeline.cache_clear()
    yield get_settings()
    db._engines.clear()


def test_seed_search_and_claim_flow(pg_settings):
    from crashcase.api.main import app
    from crashcase.pipeline.run import get_pipeline
    from crashcase.seed import PARTS_FOR_DAMAGE, synthetic_claims

    pipe = get_pipeline()
    pipe.index.add(synthetic_claims(pipe.costs, 4, pipe.embedder.dim, pipe.embedder.version))
    seeded = pipe.index.count()
    pairs = sum(len(p) for p in PARTS_FOR_DAMAGE.values())
    assert seeded == 4 * 3 * pairs  # per_group x categories x (damage, part) pairs

    with TestClient(app) as c:
        files = [("files", ("a.jpg", to_bytes(make_image(30)), "image/jpeg"))]
        body = c.post("/claims", files=files, data={"car_category": "hatchback"}).json()
        assert body["status"] == "done", body
        a = body["result"]["assessments"][0]
        assert a["basis"] == "retrieval" and len(a["similar_claims"]) == 4
        sims = [s["similarity"] for s in a["similar_claims"]]
        assert sims == sorted(sims, reverse=True)

        r = c.post(f"/claims/{body['claim_id']}/review", json={"approved": True})
        assert r.json()["status"] == "approved"
    assert pipe.index.count() == seeded + 1
