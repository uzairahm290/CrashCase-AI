"""Fraud checks: photos reused from earlier claims, and photos edited in image software."""

from __future__ import annotations

import numpy as np
from PIL import Image

EDITING_SOFTWARE = ("photoshop", "gimp", "snapseed", "lightroom", "picsart", "canva")
_SOFTWARE_TAG = 0x0131


def dhash(image: Image.Image, size: int = 16) -> str:
    """256-bit difference hash; near-identical photos have a small Hamming distance.

    16x16 rather than the usual 8x8: two different cars shot from the same angle often
    collide at 64 bits, which would wrongly flag honest claims.
    """
    g = np.asarray(image.convert("L").resize((size + 1, size)), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).ravel()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def find_duplicates(
    hashes: list[str], known: list[tuple[str, str]], max_distance: int
) -> list[tuple[str, int]]:
    """Return (earlier_claim_id, distance) for each submitted hash that matches an old one."""
    hits = []
    for h in hashes:
        for claim_id, old in known:
            d = hamming(h, old)
            if d <= max_distance:
                hits.append((claim_id, d))
                break
    return hits


def edited_with(image: Image.Image) -> str | None:
    try:
        software = str(image.getexif().get(_SOFTWARE_TAG, "")).lower()
    except Exception:
        return None
    return next((s for s in EDITING_SOFTWARE if s in software), None)
