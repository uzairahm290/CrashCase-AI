"""CrashCase AI HTTP API. Run: uvicorn crashcase.api.main:app --host 0.0.0.0 --port 8000"""

from __future__ import annotations

import io
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from crashcase import __version__
from crashcase.config import Settings, get_settings
from crashcase.db import Claim, get_sessionmaker
from crashcase.schemas import CAR_CATEGORIES, ClaimOut, ClaimResult, ClaimStatus, ReviewIn
from crashcase.storage import get_storage

log = logging.getLogger("crashcase.api")
MAX_IMAGES = 6
MAX_BYTES = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    get_sessionmaker(settings)  # creates tables
    if settings.index_backend == "memory":
        # Dev convenience: an in-memory index starts empty, so fill it with synthetic claims.
        from crashcase.pipeline.run import get_pipeline
        from crashcase.seed import synthetic_claims

        pipe = get_pipeline()
        if pipe.index.count() == 0:
            pipe.index.add(synthetic_claims(pipe.costs, 20, pipe.embedder.dim, pipe.embedder.version))
            log.info("seeded in-memory index with %d synthetic claims", pipe.index.count())
    yield


app = FastAPI(title="CrashCase AI", version=__version__, lifespan=lifespan)
Instrumentator().instrument(app).expose(app, include_in_schema=False)


def _session(settings: Settings = Depends(get_settings)):
    Session = get_sessionmaker(settings)
    with Session() as session:
        yield session


def _out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        claim_id=claim.id,
        status=ClaimStatus(claim.status),
        result=ClaimResult(**claim.result) if claim.result else None,
        error=claim.error,
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
    else:
        claim.status = ClaimStatus.declined.value
    session.commit()
    return _out(claim)
