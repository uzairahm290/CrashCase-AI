"""Damage + part segmentation.

`YoloDetector` uses two YOLOv8-seg models (damage, and optionally parts) and fuses
their masks into "dent on front_bumper, 18% coverage". `StubDetector` needs no weights
so the whole system can be deployed and tested before any model is trained.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np
from PIL import Image

from crashcase.config import Settings
from crashcase.schemas import DAMAGE_TYPES, PARTS, Detection


def normalize_label(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


class Detector(Protocol):
    version: str

    def detect(self, image: Image.Image) -> list[Detection]: ...


class StubDetector:
    """Deterministic fake detector: same image in, same detection out."""

    version = "stub-0"

    def detect(self, image: Image.Image) -> list[Detection]:
        digest = hashlib.sha1(image.tobytes()[:65536]).digest()
        w, h = image.size
        damage = DAMAGE_TYPES[digest[0] % len(DAMAGE_TYPES)]
        part = PARTS[digest[1] % (len(PARTS) - 1)]
        severity = 0.05 + (digest[2] / 255) * 0.6
        return [
            Detection(
                damage_type=damage,
                part=part,
                confidence=0.5,
                bbox=[w * 0.25, h * 0.25, w * 0.75, h * 0.75],
                severity=round(severity, 3),
            )
        ]


class YoloDetector:
    def __init__(self, damage_weights: str, parts_weights: str = "", conf: float = 0.25):
        from ultralytics import YOLO

        self.damage_model = YOLO(damage_weights)
        self.parts_model = YOLO(parts_weights) if parts_weights else None
        self.conf = conf
        self.version = f"yolo:{damage_weights}" + (f"+{parts_weights}" if parts_weights else "")

    @staticmethod
    def _masks(result) -> tuple[list[np.ndarray], list[str], list[float], list[list[float]]]:
        if result.masks is None:
            return [], [], [], []
        masks = [m.cpu().numpy() > 0.5 for m in result.masks.data]
        names = [normalize_label(result.names[int(c)]) for c in result.boxes.cls]
        confs = [float(c) for c in result.boxes.conf]
        boxes = [[float(v) for v in b] for b in result.boxes.xyxy]
        return masks, names, confs, boxes

    def detect(self, image: Image.Image) -> list[Detection]:
        dmg = self.damage_model.predict(image, conf=self.conf, verbose=False)[0]
        d_masks, d_names, d_confs, d_boxes = self._masks(dmg)

        p_masks, p_names = [], []
        if self.parts_model is not None:
            parts = self.parts_model.predict(image, conf=self.conf, verbose=False)[0]
            p_masks, p_names, _, _ = self._masks(parts)

        out: list[Detection] = []
        for mask, name, conf, box in zip(d_masks, d_names, d_confs, d_boxes, strict=True):
            part, severity = "unknown", None
            best_overlap = 0
            for p_mask, p_name in zip(p_masks, p_names, strict=True):
                overlap = int(np.logical_and(mask, p_mask).sum())
                if overlap > best_overlap:
                    best_overlap = overlap
                    part = p_name
                    severity = overlap / max(int(p_mask.sum()), 1)
            if severity is None:
                # No parts model: approximate with damage area relative to the whole image.
                severity = min(1.0, float(mask.mean()) * 4)
            out.append(
                Detection(
                    damage_type=name,
                    part=part,
                    confidence=round(conf, 3),
                    bbox=box,
                    severity=round(min(severity, 1.0), 3),
                )
            )
        return out


def build_detector(settings: Settings) -> Detector:
    if settings.detector_backend == "yolo":
        return YoloDetector(settings.damage_weights, settings.parts_weights)
    return StubDetector()
