from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

# CarDD damage classes
DAMAGE_TYPES = ["dent", "scratch", "crack", "glass_shatter", "lamp_broken", "tire_flat"]
PARTS = [
    "front_bumper",
    "rear_bumper",
    "door",
    "hood",
    "fender",
    "headlight",
    "taillight",
    "windshield",
    "tire",
    "unknown",
]
CAR_CATEGORIES = ["hatchback", "sedan", "suv"]


class ClaimStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    rejected = "rejected"  # failed quality gate
    done = "done"
    failed = "failed"
    approved = "approved"  # adjuster approved; fed back into the claim index
    declined = "declined"  # adjuster declined the assessment


class Detection(BaseModel):
    damage_type: str
    part: str
    confidence: float
    bbox: list[float] = Field(description="x1, y1, x2, y2 in pixels")
    severity: float = Field(ge=0, le=1, description="share of the part covered by damage")


class QualityResult(BaseModel):
    image: str
    blur_score: float
    brightness: float
    passed: bool
    reason: str | None = None


class SimilarClaim(BaseModel):
    claim_ref: str
    damage_type: str
    part: str
    car_category: str
    severity: float
    cost_pkr: float
    similarity: float


class DamageAssessment(BaseModel):
    detection: Detection
    image: str
    similar_claims: list[SimilarClaim]
    cost_low_pkr: float
    cost_high_pkr: float
    cost_estimate_pkr: float
    action: str  # "repair" or "replace"
    basis: str  # "retrieval" or "cost_table"


class FraudCheck(BaseModel):
    flagged: bool
    reasons: list[str] = []


class ClaimResult(BaseModel):
    claim_id: str
    car_category: str
    quality: list[QualityResult]
    assessments: list[DamageAssessment]
    total_low_pkr: float
    total_high_pkr: float
    fraud: FraudCheck
    report: str
    model_versions: dict[str, str]
    prompt_version: str
    pipeline_seconds: float


class ClaimOut(BaseModel):
    claim_id: str
    status: ClaimStatus
    result: ClaimResult | None = None
    error: str | None = None


class ReviewIn(BaseModel):
    approved: bool
    final_cost_pkr: float | None = Field(
        default=None, description="Adjuster's final total; defaults to the midpoint estimate"
    )
