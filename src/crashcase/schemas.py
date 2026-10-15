from __future__ import annotations

from datetime import datetime
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
    adjusted_cost_pkr: float | None = Field(
        default=None, description="This claim's price transferred to the current case"
    )


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
    car_category: str
    images: list[str]
    created_at: datetime
    result: ClaimResult | None = None
    error: str | None = None
    final_cost_pkr: float | None = None


class ClaimSummary(BaseModel):
    claim_id: str
    status: ClaimStatus
    car_category: str
    created_at: datetime
    images: list[str]
    damage_count: int
    total_low_pkr: float | None = None
    total_high_pkr: float | None = None
    fraud_flagged: bool = False
    final_cost_pkr: float | None = None


class Stats(BaseModel):
    claims_total: int
    by_status: dict[str, int]
    fraud_flagged: int
    avg_pipeline_seconds: float | None
    index_size: int
    approved_value_pkr: float
    damage_mix: dict[str, int]
    model_versions: dict[str, str]


class ReviewIn(BaseModel):
    approved: bool
    final_cost_pkr: float | None = Field(
        default=None, description="Adjuster's final total; defaults to the midpoint estimate"
    )
