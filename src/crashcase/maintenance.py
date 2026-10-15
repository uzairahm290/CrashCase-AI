"""Index maintenance used by the Prefect flows (and runnable by hand)."""

from __future__ import annotations

import io
import logging

from PIL import Image

from crashcase.pipeline.embedder import crop
from crashcase.pipeline.run import Pipeline
from crashcase.seed import synthetic_claims

log = logging.getLogger(__name__)


def reindex(pipe: Pipeline, per_group: int = 20) -> dict:
    """Bring every embedding in the index up to the current embedder version.

    Approved claims are re-embedded from their stored photo crop. Synthetic claims have no
    photo, so the synthetic set is regenerated with the current embedder's dimensions.
    Runs whenever the embedder changes (e.g. histogram -> CLIP), otherwise it is a no-op.
    """
    version = pipe.embedder.version
    stale = pipe.index.stale(version)
    stale = [c for c in stale if c.embedder_version != f"synthetic:{version}"]
    if not stale:
        return {"stale": 0, "reembedded": 0, "regenerated": 0, "skipped": 0}

    reembedded, skipped = [], 0
    for c in (c for c in stale if c.source == "approved"):
        if not (c.image_key and c.bbox):
            skipped += 1
            continue
        img = Image.open(io.BytesIO(pipe.storage.load(c.image_key))).convert("RGB")
        c.embedding = pipe.embedder.embed(crop(img, c.bbox))
        c.embedder_version = version
        reembedded.append(c)

    synthetic_stale = [c for c in stale if c.source == "synthetic"]
    regenerated = []
    if synthetic_stale:
        regenerated = synthetic_claims(pipe.costs, per_group, pipe.embedder.dim, version)

    # Comparing PastClaims directly would compare numpy arrays, so go by ref.
    done = {c.ref for c in reembedded}
    pipe.index.remove([c.ref for c in stale if c.source == "synthetic" or c.ref in done])
    pipe.index.add(reembedded + regenerated)
    out = {
        "stale": len(stale),
        "reembedded": len(reembedded),
        "regenerated": len(regenerated),
        "skipped": skipped,
    }
    log.info("reindex: %s", out)
    return out
