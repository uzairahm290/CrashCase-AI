"""BentoML service for damage detection.

Runs the detector as its own scalable service so the CPU/GPU-heavy model is separate from
the Celery workers. Workers call it when CC_DETECTOR_BACKEND=bento.

    bentoml serve serving.service:DamageDetector --port 3005
    CC_DETECTOR_BACKEND=yolo CC_DAMAGE_WEIGHTS=models:/crashcase-damage-seg@champion bentoml serve ...
"""

from __future__ import annotations

import bentoml
from PIL.Image import Image


@bentoml.service(
    name="crashcase-detector",
    resources={"cpu": "2"},
    traffic={"timeout": 60, "max_concurrency": 8},
)
class DamageDetector:
    def __init__(self) -> None:
        from crashcase.config import get_settings
        from crashcase.pipeline.detector import StubDetector, YoloDetector

        s = get_settings()
        # The service itself never proxies to another bento: "bento" here means "use the stub".
        if s.detector_backend == "yolo":
            self.detector = YoloDetector(s.damage_weights, s.parts_weights)
        else:
            self.detector = StubDetector()

    @bentoml.api
    def detect(self, image: Image) -> list[dict]:
        return [d.model_dump() for d in self.detector.detect(image.convert("RGB"))]

    @bentoml.api
    def version(self) -> str:
        return self.detector.version
