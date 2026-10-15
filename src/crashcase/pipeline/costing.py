"""Cost estimation: weighted by similar past claims, falling back to the cost table."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from crashcase.schemas import Detection, SimilarClaim


@dataclass(frozen=True)
class CostTable:
    replace_part_pkr: dict
    repair_fraction: dict
    category_multiplier: dict
    always_replace: list
    replace_above_severity: float
    labour_pkr: float
    noise_std: float

    def action(self, damage_type: str, severity: float) -> str:
        if damage_type in self.always_replace or severity >= self.replace_above_severity:
            return "replace"
        return "repair"

    def base_cost(self, damage_type: str, part: str, severity: float, car_category: str) -> float:
        part_price = self.replace_part_pkr.get(part, self.replace_part_pkr["unknown"])
        mult = self.category_multiplier.get(car_category, 1.0)
        if self.action(damage_type, severity) == "replace":
            cost = part_price
        else:
            # Repair cost grows with severity; at least 25% of the full-severity repair.
            frac = self.repair_fraction.get(damage_type, 0.5)
            cost = part_price * frac * max(0.25, severity / self.replace_above_severity)
        return float(cost * mult + self.labour_pkr)


@lru_cache
def load_cost_table(path: str | Path) -> CostTable:
    data = yaml.safe_load(Path(path).read_text())
    return CostTable(**data)


def estimate(
    det: Detection, car_category: str, similar: list[SimilarClaim], table: CostTable
) -> tuple[float, float, float, str]:
    """Return (estimate, low, high, basis)."""
    if similar:
        # Each neighbour is a real price for a similar case. Transfer it to this case with the
        # cost-table ratio (covers severity, repair vs replace, part and car category), then
        # weight by visual similarity. Neighbours set the price level; the table sets the shape.
        target = table.base_cost(det.damage_type, det.part, det.severity, car_category)
        costs, weights = [], []
        for s in similar:
            ref = table.base_cost(s.damage_type, s.part, s.severity, s.car_category)
            costs.append(s.cost_pkr * target / ref)
            weights.append(max(s.similarity, 0.01))
        costs_a, w = np.array(costs), np.array(weights)
        mean = float(np.average(costs_a, weights=w))
        std = float(np.sqrt(np.average((costs_a - mean) ** 2, weights=w)))
        spread = max(std, 0.10 * mean)
        return mean, max(0.0, mean - spread), mean + spread, "retrieval"

    base = table.base_cost(det.damage_type, det.part, det.severity, car_category)
    return base, base * 0.8, base * 1.2, "cost_table"
