"""Daily drift check. If recent claims drift past the threshold, start retraining."""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from crashcase.config import get_settings
from crashcase.db import get_sessionmaker


@task(retries=2, retry_delay_seconds=60)
def check(current_days: int) -> dict:
    from crashcase.monitoring.drift import run_drift_check

    settings = get_settings()
    with get_sessionmaker(settings)() as session:
        row = run_drift_check(session, settings, current_days=current_days)
        return {
            "id": row.id,
            "status": row.status,
            "drift_share": row.drift_share,
            "drifted": row.drifted_columns,
        }


@flow(name="drift-check")
def drift_check(current_days: int = 7, retrain_on_drift: bool = False) -> dict:
    log = get_run_logger()
    result = check(current_days)
    log.info("drift: %s", result)
    if result["status"] == "drift" and retrain_on_drift:
        from crashcase.flows.retrain_flow import retrain

        log.warning("drift on %s, starting retraining", result["drifted"])
        retrain(reason=f"drift on {', '.join(result['drifted'])}")
    return result
