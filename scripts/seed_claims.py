"""Fill the past-claims index.

    python scripts/seed_claims.py --per-group 20            # synthetic embeddings
    python scripts/seed_claims.py --images datasets/cardd/val   # real crops via detector + embedder

Uses the same CC_* settings as the app, so in docker-compose it writes to pgvector:
    docker compose --profile seed run --rm seed
"""

from __future__ import annotations

import argparse
import logging

from crashcase.config import get_settings
from crashcase.pipeline.costing import load_cost_table
from crashcase.pipeline.detector import build_detector
from crashcase.pipeline.embedder import build_embedder
from crashcase.pipeline.retrieval import build_index
from crashcase.seed import claims_from_images, synthetic_claims

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--per-group", type=int, default=20, help="claims per damage x part x category")
    p.add_argument("--images", help="folder of car damage photos to embed for real")
    p.add_argument("--force", action="store_true", help="seed even if the index is not empty")
    args = p.parse_args()

    s = get_settings()
    index = build_index(s)
    if index.count() and not args.force:
        log.info("index already has %d claims; use --force to add more", index.count())
        return

    table = load_cost_table(s.cost_table_path)
    embedder = build_embedder(s)
    if args.images:
        claims = claims_from_images(args.images, build_detector(s), embedder, table)
    else:
        claims = synthetic_claims(table, args.per_group, embedder.dim, embedder.version)
    index.add(claims)
    log.info("added %d claims (index now %d)", len(claims), index.count())


if __name__ == "__main__":
    main()
