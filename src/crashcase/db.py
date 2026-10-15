"""Relational storage for claims and image hashes (works on Postgres and SQLite)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from crashcase.config import Settings


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    car_category: Mapped[str] = mapped_column(String(20))
    image_keys: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ImageHash(Base):
    """Perceptual hashes of every image ever submitted, for duplicate-photo fraud checks."""

    __tablename__ = "image_hashes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    dhash: Mapped[str] = mapped_column(String(16), index=True)


_engines: dict[str, sessionmaker] = {}


def get_sessionmaker(settings: Settings) -> sessionmaker:
    url = settings.database_url
    if url not in _engines:
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        engine = create_engine(url, pool_pre_ping=True, **kwargs)
        Base.metadata.create_all(engine)
        _engines[url] = sessionmaker(engine, expire_on_commit=False)
    return _engines[url]


def known_hashes(session: Session, exclude_claim: str) -> list[tuple[str, str]]:
    rows = session.execute(
        select(ImageHash.claim_id, ImageHash.dhash).where(ImageHash.claim_id != exclude_claim)
    )
    return [(r.claim_id, r.dhash) for r in rows]
