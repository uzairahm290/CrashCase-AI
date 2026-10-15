"""Claim report: LLM grounded on the detections + retrieved claims, with a template fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from crashcase.config import Settings
from crashcase.schemas import DamageAssessment, FraudCheck

log = logging.getLogger(__name__)
PROMPT_DIR = Path("configs/prompts")


def _pkr(v: float) -> str:
    return f"PKR {round(v, -2):,.0f}"


def build_facts(car_category, assessments, fraud, total_low, total_high) -> dict:
    return {
        "car_category": car_category,
        "damages": [
            {
                "damage_type": a.detection.damage_type,
                "part": a.detection.part,
                "severity_pct": round(a.detection.severity * 100),
                "action": a.action,
                "cost_low_pkr": round(a.cost_low_pkr, -2),
                "cost_high_pkr": round(a.cost_high_pkr, -2),
                "basis": a.basis,
                "similar_claim_refs": [s.claim_ref for s in a.similar_claims],
            }
            for a in assessments
        ],
        "fraud_flags": fraud.reasons,
        "total_low_pkr": round(total_low, -2),
        "total_high_pkr": round(total_high, -2),
    }


def template_report(
    car_category, assessments: list[DamageAssessment], fraud: FraudCheck, total_low: float, total_high: float
) -> str:
    lines = []
    if fraud.flagged:
        lines.append("Attention: " + "; ".join(fraud.reasons))
        lines.append("")
    lines.append(f"Vehicle category: {car_category}")
    if not assessments:
        lines.append("No damage was detected in the submitted photos.")
    for a in assessments:
        d = a.detection
        refs = ", ".join(s.claim_ref for s in a.similar_claims) or "cost table"
        lines.append(
            f"- {d.damage_type.replace('_', ' ')} on {d.part.replace('_', ' ')}: "
            f"{round(d.severity * 100)}% severity, {a.action}, "
            f"{_pkr(a.cost_low_pkr)} to {_pkr(a.cost_high_pkr)} (based on {refs})"
        )
    lines.append("")
    lines.append(f"Total estimate: {_pkr(total_low)} to {_pkr(total_high)}.")
    lines.append("An adjuster must confirm this assessment before payout.")
    return "\n".join(lines)


def llm_report(facts: dict, settings: Settings) -> str:
    prompt = (PROMPT_DIR / f"{settings.prompt_version}.txt").read_text()
    prompt = prompt.replace("{facts}", json.dumps(facts, indent=2))
    resp = httpx.post(
        f"{settings.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 500,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def write_report(
    car_category, assessments, fraud, total_low, total_high, settings: Settings
) -> tuple[str, str]:
    """Return (report_text, generator) where generator is 'llm:<model>' or 'template'."""
    if settings.llm_api_key:
        facts = build_facts(car_category, assessments, fraud, total_low, total_high)
        try:
            return llm_report(facts, settings), f"llm:{settings.llm_model}"
        except Exception as exc:  # network, quota, etc. -> never fail the claim over the report
            log.warning("LLM report failed, using template: %s", exc)
    return template_report(car_category, assessments, fraud, total_low, total_high), "template"
