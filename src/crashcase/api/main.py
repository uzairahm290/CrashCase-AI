"""CrashCase AI HTTP API. Run: uvicorn crashcase.api.main:app --host 0.0.0.0 --port 8000"""

from __future__ import annotations

import io
import logging
import mimetypes
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select, text

from crashcase import __version__
from crashcase.config import Settings, get_settings
from crashcase.db import Claim, get_sessionmaker
from crashcase.schemas import (
    CAR_CATEGORIES,
    ClaimOut,
    ClaimResult,
    ClaimStatus,
    ClaimSummary,
    ReviewIn,
    Stats,
)
from crashcase.storage import get_storage

log = logging.getLogger("crashcase.api")
MAX_IMAGES = 6
MAX_BYTES = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    get_sessionmaker(settings)  # creates tables
    if settings.auto_seed:
        from crashcase.pipeline.run import get_pipeline
        from crashcase.seed import synthetic_claims

        pipe = get_pipeline()
        if pipe.index.count() == 0:
            pipe.index.add(synthetic_claims(pipe.costs, 20, pipe.embedder.dim, pipe.embedder.version))
            log.info("seeded claim index with %d synthetic claims", pipe.index.count())
    yield


app = FastAPI(title="CrashCase AI", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator().instrument(app).expose(app, include_in_schema=False)


def _session(settings: Settings = Depends(get_settings)):
    Session = get_sessionmaker(settings)
    with Session() as session:
        yield session


def _names(claim: Claim) -> list[str]:
    return [k.split("/", 1)[1] for k in claim.image_keys or []]


def _out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        claim_id=claim.id,
        status=ClaimStatus(claim.status),
        car_category=claim.car_category,
        images=_names(claim),
        created_at=claim.created_at,
        result=ClaimResult(**claim.result) if claim.result else None,
        error=claim.error,
        final_cost_pkr=claim.final_cost_pkr,
    )


def _summary(claim: Claim) -> ClaimSummary:
    r = claim.result or {}
    return ClaimSummary(
        claim_id=claim.id,
        status=ClaimStatus(claim.status),
        car_category=claim.car_category,
        created_at=claim.created_at,
        images=_names(claim),
        damage_count=len(r.get("assessments", [])),
        total_low_pkr=r.get("total_low_pkr"),
        total_high_pkr=r.get("total_high_pkr"),
        fraud_flagged=bool(r.get("fraud", {}).get("flagged")),
        final_cost_pkr=claim.final_cost_pkr,
    )


@app.get("/health")
def health(session=Depends(_session)):
    session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


@app.post("/claims", response_model=ClaimOut, status_code=202)
async def create_claim(
    files: list[UploadFile] = File(..., description="2-6 photos of the damaged car"),
    car_category: str = Form("sedan"),
    settings: Settings = Depends(get_settings),
    session=Depends(_session),
):
    if car_category not in CAR_CATEGORIES:
        raise HTTPException(422, f"car_category must be one of {CAR_CATEGORIES}")
    if not 1 <= len(files) <= MAX_IMAGES:
        raise HTTPException(422, f"send between 1 and {MAX_IMAGES} images")

    claim = Claim(car_category=car_category, status=ClaimStatus.queued.value, image_keys=[])
    session.add(claim)
    session.flush()

    storage = get_storage(settings)
    keys = []
    for i, f in enumerate(files):
        data = await f.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than 10 MB")
        try:
            Image.open(io.BytesIO(data)).verify()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(422, f"{f.filename} is not a valid image") from None
        name = f"{i}_{Path(f.filename or 'image.jpg').name}"
        keys.append(storage.save(f"{claim.id}/{name}", data))
    claim.image_keys = keys
    session.commit()

    if settings.inline_processing:
        from crashcase.pipeline.run import process_claim

        process_claim(claim.id)
        session.refresh(claim)
    else:
        from crashcase.worker.tasks import process_claim_task

        process_claim_task.delay(claim.id)
    return _out(claim)


@app.get("/claims", response_model=list[ClaimSummary])
def list_claims(
    status: ClaimStatus | None = None,
    limit: int = Query(50, le=200),
    session=Depends(_session),
):
    q = select(Claim).order_by(Claim.created_at.desc()).limit(limit)
    if status:
        q = q.where(Claim.status == status.value)
    return [_summary(c) for c in session.scalars(q)]


@app.get("/stats", response_model=Stats)
def stats(session=Depends(_session)):
    from crashcase.pipeline.run import get_pipeline

    claims = list(session.scalars(select(Claim)))
    results = [c.result for c in claims if c.result]
    secs = [r["pipeline_seconds"] for r in results]
    pipe = get_pipeline()
    return Stats(
        claims_total=len(claims),
        by_status=dict(Counter(c.status for c in claims)),
        fraud_flagged=sum(1 for r in results if r["fraud"]["flagged"]),
        avg_pipeline_seconds=round(sum(secs) / len(secs), 3) if secs else None,
        index_size=pipe.index.count(),
        approved_value_pkr=sum(c.final_cost_pkr or 0 for c in claims if c.status == "approved"),
        damage_mix=dict(Counter(a["detection"]["damage_type"] for r in results for a in r["assessments"])),
        model_versions={"detector": pipe.detector.version, "embedder": pipe.embedder.version},
    )


@app.get("/claims/{claim_id}/images/{name}")
def claim_image(
    claim_id: str, name: str, settings: Settings = Depends(get_settings), session=Depends(_session)
):
    claim = session.get(Claim, claim_id)
    key = f"{claim_id}/{name}"
    if claim is None or key not in (claim.image_keys or []):
        raise HTTPException(404, "image not found")
    data = get_storage(settings).load(key)
    media = mimetypes.guess_type(name)[0] or "image/jpeg"
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: str, session=Depends(_session)):
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(404, "claim not found")
    return _out(claim)


@app.post("/claims/{claim_id}/review", response_model=ClaimOut)
def review_claim(claim_id: str, review: ReviewIn, session=Depends(_session)):
    """Adjuster decision. Approved claims are added to the index (feedback loop)."""
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(404, "claim not found")
    if claim.status != ClaimStatus.done.value:
        raise HTTPException(409, f"claim is {claim.status}, only processed claims can be reviewed")

    if review.approved:
        from crashcase.pipeline.run import get_pipeline

        result = ClaimResult(**claim.result)
        final = review.final_cost_pkr or (result.total_low_pkr + result.total_high_pkr) / 2
        get_pipeline().learn_from_review(result, final)
        claim.status = ClaimStatus.approved.value
        claim.final_cost_pkr = round(final, -2)
    else:
        claim.status = ClaimStatus.declined.value
    claim.reviewed_at = datetime.now(UTC)
    session.commit()
    return _out(claim)
