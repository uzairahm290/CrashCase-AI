"""Re-embed the claim index after the embedding model changes."""

from __future__ import annotations

from prefect import flow, get_run_logger


@flow(name="reindex-claims")
def reindex_claims(per_group: int = 20) -> dict:
    from crashcase.maintenance import reindex
    from crashcase.pipeline.run import get_pipeline

    result = reindex(get_pipeline(), per_group=per_group)
    get_run_logger().info("reindex: %s", result)
    return result
