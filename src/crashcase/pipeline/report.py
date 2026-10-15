"""Claim report: LLM grounded on the detections + retrieved claims, with a template fallback."""

from __future__ import annotations

import json
import logging
import re
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


REF = re.compile(r"PC-[0-9a-f]{8}")


def citations_valid(text: str, facts: dict) -> tuple[bool, list[str]]:
    """Faithfulness guard: every claim ref the report cites must be one we retrieved."""
    known = {ref for d in facts["damages"] for ref in d["similar_claim_refs"]}
    unknown = sorted(set(REF.findall(text)) - known)
    return not unknown, unknown


class _Tracer:
    """Langfuse tracing when keys are set; a no-op otherwise."""

    def __init__(self, settings: Settings):
        self.client = None
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            try:
                from langfuse import Langfuse

                self.client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            except Exception as exc:
                log.warning("Langfuse disabled: %s", exc)

    def start(self, facts: dict, settings: Settings, prompt: str):
        if not self.client:
            return None, None
        trace = self.client.trace(
            name="claim-report",
            input=facts,
            tags=[f"prompt:{settings.prompt_version}", f"car:{facts['car_category']}"],
            metadata={"damages": len(facts["damages"]), "fraud": bool(facts["fraud_flags"])},
        )
        gen = trace.generation(
            name="report",
            model=settings.llm_model,
            input=[{"role": "user", "content": prompt}],
            model_parameters={"temperature": 0.2, "max_tokens": 500},
            metadata={"prompt_version": settings.prompt_version},
        )
        return trace, gen


_tracer: _Tracer | None = None


def _get_tracer(settings: Settings) -> _Tracer:
    global _tracer
    if _tracer is None:
        _tracer = _Tracer(settings)
    return _tracer


def render_prompt(facts: dict, settings: Settings) -> str:
    prompt = (PROMPT_DIR / f"{settings.prompt_version}.txt").read_text()
    return prompt.replace("{facts}", json.dumps(facts, indent=2))


def llm_report(facts: dict, settings: Settings) -> tuple[str, bool]:
    """Return (text, citations_ok). Traced to Langfuse with token usage and a faithfulness score."""
    prompt = render_prompt(facts, settings)
    trace, gen = _get_tracer(settings).start(facts, settings, prompt)
    try:
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
        body = resp.json()
    except Exception as exc:
        if gen:
            gen.end(level="ERROR", status_message=str(exc))
        raise
    text = body["choices"][0]["message"]["content"].strip()
    ok, unknown = citations_valid(text, facts)
    if gen:
        usage = body.get("usage") or {}
        gen.end(
            output=text,
            usage={"input": usage.get("prompt_tokens"), "output": usage.get("completion_tokens")},
        )
        trace.score(name="citations_valid", value=1 if ok else 0, comment=", ".join(unknown) or None)
    return text, ok


def llm_enabled(settings: Settings) -> bool:
    # ECS injects "none" when no key is configured (SSM parameters cannot be empty).
    return bool(settings.llm_api_key) and settings.llm_api_key != "none"


def write_report(
    car_category, assessments, fraud, total_low, total_high, settings: Settings
) -> tuple[str, str]:
    """Return (report_text, generator): 'llm:<model>', 'template' or 'template:unfaithful-llm'."""
    if llm_enabled(settings):
        facts = build_facts(car_category, assessments, fraud, total_low, total_high)
        try:
            text, ok = llm_report(facts, settings)
            if ok:
                return text, f"llm:{settings.llm_model}"
            log.warning("LLM report cited claims it was not given; using the template")
            fallback = template_report(car_category, assessments, fraud, total_low, total_high)
            return fallback, "template:unfaithful-llm"
        except Exception as exc:  # network, quota, etc. -> never fail the claim over the report
            log.warning("LLM report failed, using template: %s", exc)
    return template_report(car_category, assessments, fraud, total_low, total_high), "template"
