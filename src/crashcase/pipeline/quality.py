"""Quality gate: reject blurry or badly lit photos before spending GPU time on them."""

from __future__ import annotations

import numpy as np
from PIL import Image

from crashcase.config import Settings
from crashcase.schemas import QualityResult

_LAPLACIAN = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)


def blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian; low values mean a blurry image."""
    g = gray.astype(np.float32)
    h, w = g.shape
    out = np.zeros((h - 2, w - 2), dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            k = _LAPLACIAN[dy, dx]
            if k:
                out += k * g[dy : dy + h - 2, dx : dx + w - 2]
    return float(out.var())


def check_quality(name: str, image: Image.Image, settings: Settings) -> QualityResult:
    gray = np.asarray(image.convert("L").resize((512, 512)))
    blur = blur_score(gray)
    brightness = float(gray.mean())

    # Lighting first: a dark photo also has low contrast, so it would look "blurry" too.
    reason = None
    if brightness < settings.min_brightness:
        reason = "too dark, please retake in better light"
    elif brightness > settings.max_brightness:
        reason = "overexposed, please retake"
    elif blur < settings.min_blur_score:
        reason = "too blurry, please retake"

    return QualityResult(
        image=name,
        blur_score=round(blur, 2),
        brightness=round(brightness, 2),
        passed=reason is None,
        reason=reason,
    )
