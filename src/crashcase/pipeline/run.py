"""The claim pipeline: quality gate -> detect -> embed -> retrieve -> cost -> fraud -> report."""

from __future__ import annotations

import io
import logging
import time
from contextlib import contextmanager
from functools import lru_cache

from PIL import Image

from crashcase import metrics
from crashcase.config import Settings, get_settings
from crashcase.db import Claim, ImageHash, get_sessionmaker, known_hashes
from crashcase.pipeline import costing, fraud
from crashcase.pipeline.detector import build_detector
from crashcase.pipeline.embedder import build_embedder, crop
from crashcase.pipeline.quality import check_quality
from crashcase.pipeline.report import write_report
from crashcase.pipeline.retrieval import PastClaim, build_index
from crashcase.schemas import ClaimResult, ClaimStatus, DamageAssessment, FraudCheck
from crashcase.storage import get_storage

log = logging.getLogger(__name__)


def _display(name: str) -> str:
    """Stored names are "<index>_<original>"; show the original file name."""
    return name.split("_", 1)[1] if "_" in name and name.split("_", 1)[0].isdigit() else name


@contextmanager
def _stage(name: str):
    start = time.perf_counter()
    yield
    metrics.STAGE_SECONDS.labels(stage=name).observe(time.perf_counter() - start)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector = build_detector(settings)
        self.embedder = build_embedder(settings)
        self.index = build_index(settings)
        self.costs = costing.load_cost_table(settings.cost_table_path)
        self.storage = get_storage(settings)

    def assess(
        self, claim_id: str, car_category: str, images: dict[str, Image.Image], known: list[tuple[str, str]]
    ) -> tuple[ClaimResult, list[str]]:
        """Pure assessment step. Returns the result and the image hashes to remember."""
        s = self.settings
        start = time.perf_counter()

        # EXIF must be read before converting, since conversion drops it.
        edited = {name: fraud.edited_with(img) for name, img in images.items()}
        images = {name: img.convert("RGB") for name, img in images.items()}

        with _stage("quality"):
            quality = [check_quality(name, img, s) for name, img in images.items()]
        good = {q.image: images[q.image] for q in quality if q.passed}

        assessments: list[DamageAssessment] = []
        for name, img in good.items():
            with _stage("detect"):
                detections = self.detector.detect(img)
            for det in detections:
                metrics.DETECTIONS.labels(damage_type=det.damage_type).inc()
                with _stage("embed"):
                    vec = self.embedder.embed(crop(img, det.bbox))
                with _stage("retrieve"):
                    similar = self.index.search(vec, det.damage_type, car_category, det.part, s.top_k)
                if similar:
                    metrics.RETRIEVAL_HITS.observe(similar[0].similarity)
                est, low, high, basis = costing.estimate(det, car_category, similar, self.costs)
                assessments.append(
                    DamageAssessment(
                        detection=det,
                        image=name,
                        similar_claims=similar,
                        cost_estimate_pkr=round(est, -2),
                        cost_low_pkr=round(low, -2),
                        cost_high_pkr=round(high, -2),
                        action=self.costs.action(det.damage_type, det.severity),
                        basis=basis,
                    )
                )

        with _stage("fraud"):
            hashes = [fraud.dhash(img) for img in images.values()]
            reasons = []
            for name, h in zip(images, hashes, strict=True):
                for cid, _ in fraud.find_duplicates([h], known, s.duplicate_hash_distance):
                    reasons.append(
                        f"Photo {_display(name)} is the same photo as one in claim {cid[:8].upper()}"
                    )
            reasons += [
                f"Photo {_display(name)} was edited in {tool.title()}"
                for name, tool in edited.items()
                if tool
            ]
        fraud_check = FraudCheck(flagged=bool(reasons), reasons=reasons)
        if fraud_check.flagged:
            metrics.FRAUD_FLAGS.inc()

        total_low = sum(a.cost_low_pkr for a in assessments)
        total_high = sum(a.cost_high_pkr for a in assessments)
        with _stage("report"):
            report, generator = write_report(car_category, assessments, fraud_check, total_low, total_high, s)
        metrics.REPORTS.labels(generator=generator).inc()

        elapsed = time.perf_counter() - start
        metrics.PIPELINE_SECONDS.observe(elapsed)
        result = ClaimResult(
            claim_id=claim_id,
            car_category=car_category,
            quality=quality,
            assessments=assessments,
            total_low_pkr=total_low,
            total_high_pkr=total_high,
            fraud=fraud_check,
            report=report,
            model_versions={
                "detector": self.detector.version,
                "embedder": self.embedder.version,
                "report": generator,
            },
            prompt_version=s.prompt_version,
            pipeline_seconds=round(elapsed, 3),
        )
        return result, hashes

    def learn_from_review(self, result: ClaimResult, final_total: float) -> int:
        """Feedback loop: an approved claim becomes retrieval evidence for future claims."""
        if not result.assessments:
            return 0
        est_total = sum(a.cost_estimate_pkr for a in result.assessments) or 1.0
        scale = final_total / est_total
        new = []
        for a in result.assessments:
            img = Image.open(io.BytesIO(self.storage.load(f"{result.claim_id}/{a.image}")))
            new.append(
                PastClaim(
                    damage_type=a.detection.damage_type,
                    part=a.detection.part,
                    car_category=result.car_category,
                    severity=a.detection.severity,
                    cost_pkr=round(a.cost_estimate_pkr * scale, -2),
                    embedding=self.embedder.embed(crop(img, a.detection.bbox)),
                    source="approved",
                    embedder_version=self.embedder.version,
                )
            )
        self.index.add(new)
        return len(new)


@lru_cache
def get_pipeline() -> Pipeline:
    return Pipeline(get_settings())


def process_claim(claim_id: str) -> None:
    """Load a queued claim, run the pipeline, store the result. Called by the Celery worker."""
    settings = get_settings()
    pipe = get_pipeline()
    Session = get_sessionmaker(settings)

    with Session() as session:
        claim = session.get(Claim, claim_id)
        if claim is None:
            raise ValueError(f"claim {claim_id} not found")
        claim.status = ClaimStatus.processing.value
        session.commit()
        try:
            images = {
                key.split("/", 1)[1]: Image.open(io.BytesIO(pipe.storage.load(key)))
                for key in claim.image_keys
            }
            known = known_hashes(session, claim_id)
            result, hashes = pipe.assess(claim_id, claim.car_category, images, known)
            session.add_all(ImageHash(claim_id=claim_id, dhash=h) for h in hashes)
            all_rejected = not any(q.passed for q in result.quality)
            claim.status = (ClaimStatus.rejected if all_rejected else ClaimStatus.done).value
            claim.result = result.model_dump(mode="json")
        except Exception as exc:
            log.exception("claim %s failed", claim_id)
            claim.status = ClaimStatus.failed.value
            claim.error = str(exc)
        session.commit()
        metrics.CLAIMS_PROCESSED.labels(status=claim.status).inc()
