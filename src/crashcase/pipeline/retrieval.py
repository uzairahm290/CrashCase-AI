"""Vector index of past claims: pgvector in production, in-memory for tests and dev."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from crashcase.config import Settings
from crashcase.schemas import SimilarClaim


@dataclass
class PastClaim:
    damage_type: str
    part: str
    car_category: str
    severity: float
    cost_pkr: float
    embedding: np.ndarray
    source: str = "synthetic"  # "synthetic" | "approved"
    embedder_version: str = ""
    ref: str = field(default_factory=lambda: f"PC-{uuid.uuid4().hex[:8]}")


class ClaimIndex(Protocol):
    def add(self, claims: list[PastClaim]) -> None: ...
    def search(
        self, embedding: np.ndarray, damage_type: str, car_category: str, part: str | None, k: int
    ) -> list[SimilarClaim]: ...
    def count(self) -> int: ...


def _to_similar(c: PastClaim, sim: float) -> SimilarClaim:
    return SimilarClaim(
        claim_ref=c.ref,
        damage_type=c.damage_type,
        part=c.part,
        car_category=c.car_category,
        severity=c.severity,
        cost_pkr=c.cost_pkr,
        similarity=round(float(sim), 4),
    )


class InMemoryIndex:
    def __init__(self) -> None:
        self._items: list[PastClaim] = []
        self._lock = threading.Lock()

    def add(self, claims: list[PastClaim]) -> None:
        with self._lock:
            self._items.extend(claims)

    def count(self) -> int:
        return len(self._items)

    def search(self, embedding, damage_type, car_category, part, k):
        pool = [c for c in self._items if c.damage_type == damage_type and c.car_category == car_category]
        if part and part != "unknown":
            same_part = [c for c in pool if c.part == part]
            if len(same_part) >= k:
                pool = same_part
        if not pool:
            return []
        mat = np.stack([c.embedding for c in pool])
        sims = mat @ embedding
        order = np.argsort(-sims)[:k]
        return [_to_similar(pool[i], sims[i]) for i in order]


class PgVectorIndex:
    """past_claims table with a pgvector column; cosine distance via the <=> operator."""

    def __init__(self, database_url: str, dim: int):
        from pgvector.sqlalchemy import Vector
        from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, text

        self.engine = create_engine(database_url, pool_pre_ping=True)
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        meta = MetaData()
        self.table = Table(
            "past_claims",
            meta,
            Column("ref", String(32), primary_key=True),
            Column("damage_type", String(32), index=True),
            Column("part", String(32), index=True),
            Column("car_category", String(16), index=True),
            Column("severity", Float),
            Column("cost_pkr", Float),
            Column("source", String(16)),
            Column("embedder_version", String(64)),
            Column("embedding", Vector(dim)),
        )
        meta.create_all(self.engine)

    def add(self, claims: list[PastClaim]) -> None:
        if not claims:
            return
        rows = [
            {
                "ref": c.ref,
                "damage_type": c.damage_type,
                "part": c.part,
                "car_category": c.car_category,
                "severity": c.severity,
                "cost_pkr": c.cost_pkr,
                "source": c.source,
                "embedder_version": c.embedder_version,
                "embedding": c.embedding.tolist(),
            }
            for c in claims
        ]
        with self.engine.begin() as conn:
            conn.execute(self.table.insert(), rows)

    def count(self) -> int:
        from sqlalchemy import func, select

        with self.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(self.table)).scalar_one()

    def _query(self, embedding, damage_type, car_category, part, k):
        from sqlalchemy import select

        t = self.table
        dist = t.c.embedding.cosine_distance(embedding.tolist()).label("dist")
        q = select(t, dist).where(t.c.damage_type == damage_type, t.c.car_category == car_category)
        if part:
            q = q.where(t.c.part == part)
        with self.engine.connect() as conn:
            return conn.execute(q.order_by(dist).limit(k)).all()

    def search(self, embedding, damage_type, car_category, part, k):
        rows = []
        if part and part != "unknown":
            rows = self._query(embedding, damage_type, car_category, part, k)
        if len(rows) < k:
            rows = self._query(embedding, damage_type, car_category, None, k)
        return [
            SimilarClaim(
                claim_ref=r.ref,
                damage_type=r.damage_type,
                part=r.part,
                car_category=r.car_category,
                severity=r.severity,
                cost_pkr=r.cost_pkr,
                similarity=round(1 - float(r.dist), 4),
            )
            for r in rows
        ]


_memory_index = InMemoryIndex()


def build_index(settings: Settings) -> ClaimIndex:
    if settings.index_backend == "pgvector":
        return PgVectorIndex(settings.database_url, settings.embed_dim)
    return _memory_index
