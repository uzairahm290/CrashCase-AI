"""Synthetic past-claims database.

No public dataset has repair costs, so we generate claims from configs/cost_table.yaml
with realistic noise. Two embedding modes:
- synthetic: one random cluster centre per (damage, part), plus noise. Works with no images.
- from images: run the real detector + embedder over a folder (e.g. CarDD val split), so
  retrieval compares real crops with real crops. Use this once a model is trained.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from crashcase.pipeline.costing import CostTable
from crashcase.pipeline.embedder import Embedder, crop
from crashcase.pipeline.retrieval import PastClaim
from crashcase.schemas import CAR_CATEGORIES, DAMAGE_TYPES

PARTS_FOR_DAMAGE = {
    "dent": ["front_bumper", "rear_bumper", "door", "hood", "fender"],
    "scratch": ["front_bumper", "rear_bumper", "door", "hood", "fender"],
    "crack": ["front_bumper", "rear_bumper", "fender"],
    "glass_shatter": ["windshield"],
    "lamp_broken": ["headlight", "taillight"],
    "tire_flat": ["tire"],
}


def _noisy_cost(table: CostTable, damage, part, severity, category, rng) -> float:
    base = table.base_cost(damage, part, severity, category)
    return float(round(base * rng.lognormal(0, table.noise_std), -2))


def synthetic_claims(
    table: CostTable, per_group: int, dim: int, version: str, seed: int = 42
) -> list[PastClaim]:
    rng = np.random.default_rng(seed)
    claims = []
    for damage in DAMAGE_TYPES:
        for part in PARTS_FOR_DAMAGE[damage]:
            centre = rng.normal(size=dim)
            for category in CAR_CATEGORIES:
                for _ in range(per_group):
                    severity = float(np.clip(rng.beta(2, 4), 0.02, 0.95))
                    vec = centre + rng.normal(scale=0.6, size=dim)
                    vec = (vec / np.linalg.norm(vec)).astype(np.float32)
                    claims.append(
                        PastClaim(
                            damage_type=damage,
                            part=part,
                            car_category=category,
                            severity=round(severity, 3),
                            cost_pkr=_noisy_cost(table, damage, part, severity, category, rng),
                            embedding=vec,
                            source="synthetic",
                            embedder_version=f"synthetic:{version}",
                        )
                    )
    return claims


def claims_from_images(
    folder: Path, detector, embedder: Embedder, table: CostTable, seed: int = 42
) -> list[PastClaim]:
    rng = np.random.default_rng(seed)
    claims = []
    files = sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    for path in files:
        img = Image.open(path).convert("RGB")
        category = CAR_CATEGORIES[int(rng.integers(len(CAR_CATEGORIES)))]
        for det in detector.detect(img):
            claims.append(
                PastClaim(
                    damage_type=det.damage_type,
                    part=det.part,
                    car_category=category,
                    severity=det.severity,
                    cost_pkr=_noisy_cost(table, det.damage_type, det.part, det.severity, category, rng),
                    embedding=embedder.embed(crop(img, det.bbox)),
                    source="synthetic",
                    embedder_version=embedder.version,
                )
            )
    return claims
