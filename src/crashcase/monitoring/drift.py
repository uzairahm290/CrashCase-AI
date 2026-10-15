"""Data drift: are recent claims different from the ones the system was tuned on?

Compares a reference window of claims with the most recent window using Evidently, on two
levels: photos (brightness, sharpness) and detected damage (severity, model confidence,
damage type, part, cost). Photos from a new phone model, a monsoon month of dark photos or
a shift in damage types all show up here before they show up as bad estimates.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import select

from crashcase.config import Settings
from crashcase.db import Claim, DriftReport
from crashcase.storage import get_storage

log = logging.getLogger(__name__)

PHOTO_COLS = ["brightness", "blur_score"]
DAMAGE_NUM = ["severity", "confidence", "cost_estimate_pkr"]
DAMAGE_CAT = ["damage_type", "part"]


def frames(claims: list[Claim]) -> tuple[pd.DataFrame, pd.DataFrame]:
    photos, damage = [], []
    for c in claims:
        r = c.result or {}
        photos += [{k: q[k] for k in PHOTO_COLS} for q in r.get("quality", [])]
        for a in r.get("assessments", []):
            d = a["detection"]
            damage.append(
                {
                    "severity": d["severity"],
                    "confidence": d["confidence"],
                    "damage_type": d["damage_type"],
                    "part": d["part"],
                    "cost_estimate_pkr": a["cost_estimate_pkr"],
                }
            )
    return pd.DataFrame(photos, columns=PHOTO_COLS), pd.DataFrame(damage, columns=DAMAGE_NUM + DAMAGE_CAT)


def _drift(ref: pd.DataFrame, cur: pd.DataFrame, numerical: list[str], categorical: list[str]):
    from evidently import ColumnMapping
    from evidently.metric_preset import DataDriftPreset
    from evidently.report import Report

    report = Report(metrics=[DataDriftPreset()])
    report.run(
        reference_data=ref,
        current_data=cur,
        column_mapping=ColumnMapping(numerical_features=numerical, categorical_features=categorical),
    )
    result = report.as_dict()["metrics"][0]["result"]
    drifted = [
        col
        for col, info in report.as_dict()["metrics"][1]["result"]["drift_by_columns"].items()
        if info["drift_detected"]
    ]
    return report, result["share_of_drifted_columns"], drifted


def run_drift_check(session, settings: Settings, current_days: int = 7, min_rows: int = 20) -> DriftReport:
    """Reference = claims older than `current_days`; current = the last `current_days`."""
    cutoff = datetime.now(UTC) - timedelta(days=current_days)
    done = ("done", "approved", "declined", "rejected")
    claims = list(session.scalars(select(Claim).where(Claim.status.in_(done)).order_by(Claim.created_at)))
    ref_claims = [c for c in claims if _aware(c.created_at) < cutoff]
    cur_claims = [c for c in claims if _aware(c.created_at) >= cutoff]
    if len(ref_claims) < min_rows:  # young system: split what we have in half by time
        half = len(claims) // 2
        ref_claims, cur_claims = claims[:half], claims[half:]

    ref_p, ref_d = frames(ref_claims)
    cur_p, cur_d = frames(cur_claims)

    row = DriftReport(n_reference=len(ref_d), n_current=len(cur_d))
    if min(len(ref_p), len(cur_p), len(ref_d), len(cur_d)) < min_rows:
        row.status = "not_enough_data"
        row.summary = {"needed": min_rows, "reference": len(ref_d), "current": len(cur_d)}
        session.add(row)
        session.commit()
        return row

    photo_report, photo_share, photo_drifted = _drift(ref_p, cur_p, PHOTO_COLS, [])
    dmg_report, dmg_share, dmg_drifted = _drift(ref_d, cur_d, DAMAGE_NUM, DAMAGE_CAT)

    drifted = photo_drifted + dmg_drifted
    share = len(drifted) / (len(PHOTO_COLS) + len(DAMAGE_NUM) + len(DAMAGE_CAT))
    row.status = "drift" if share >= settings.drift_share_threshold else "ok"
    row.drift_share = round(share, 3)
    row.drifted_columns = drifted
    row.summary = {"photo_share": photo_share, "damage_share": dmg_share}

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    storage = get_storage(settings)
    row.report_key = storage.save(f"reports/drift-{stamp}-damage.html", _html(dmg_report))
    storage.save(f"reports/drift-{stamp}-photos.html", _html(photo_report))
    session.add(row)
    session.commit()
    log.info("drift check: %s, drifted=%s", row.status, drifted)
    return row


def _html(report) -> bytes:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".html") as f:
        report.save_html(f.name)
        return open(f.name, "rb").read()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
