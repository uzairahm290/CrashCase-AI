"""Image embeddings for similar-claim retrieval.

`ClipEmbedder` (open_clip ViT-B/32, 512-d) is the real one. `HistogramEmbedder` is a
512-d RGB colour histogram (8x8x8 bins) so retrieval works with zero ML dependencies.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from PIL import Image

from crashcase.config import Settings


class Embedder(Protocol):
    version: str
    dim: int

    def embed(self, image: Image.Image) -> np.ndarray: ...


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)


class HistogramEmbedder:
    version = "rgb-hist-8x8x8"
    dim = 512

    def embed(self, image: Image.Image) -> np.ndarray:
        arr = np.asarray(image.convert("RGB").resize((128, 128))) // 32  # 0..7
        idx = arr[..., 0].astype(np.int32) * 64 + arr[..., 1] * 8 + arr[..., 2]
        hist = np.bincount(idx.ravel(), minlength=512).astype(np.float32)
        return _l2(np.sqrt(hist))


class ClipEmbedder:
    dim = 512

    def __init__(self, model_name: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"):
        import open_clip
        import torch

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained
        )
        self.model.eval()
        self.version = f"open_clip:{model_name}:{pretrained}"

    def embed(self, image: Image.Image) -> np.ndarray:
        with self.torch.no_grad():
            x = self.preprocess(image.convert("RGB")).unsqueeze(0)
            v = self.model.encode_image(x)[0].cpu().numpy()
        return _l2(v)


def crop(image: Image.Image, bbox: list[float], pad: float = 0.1) -> Image.Image:
    x1, y1, x2, y2 = bbox
    w, h = image.size
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    box = (max(0, x1 - px), max(0, y1 - py), min(w, x2 + px), min(h, y2 + py))
    return image.crop(tuple(int(v) for v in box))


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder_backend == "clip":
        return ClipEmbedder()
    return HistogramEmbedder()
