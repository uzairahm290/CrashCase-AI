import io

import numpy as np
import pytest
from PIL import Image


def make_image(seed: int = 0, size=(320, 240), brightness: float = 1.0, blur: bool = False) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(40, 215, size=(size[1], size[0], 3)).astype(np.float32)
    if blur:
        arr[:] = arr.mean(axis=(0, 1))  # flat image: no edges at all
    arr = np.clip(arr * brightness, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def to_bytes(img: Image.Image, fmt: str = "JPEG", exif=None) -> bytes:
    buf = io.BytesIO()
    if exif is not None:
        img.save(buf, fmt, exif=exif)
    else:
        img.save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("CC_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CC_INLINE_PROCESSING", "true")
    monkeypatch.setenv("CC_INDEX_BACKEND", "memory")
    monkeypatch.setenv("CC_LLM_API_KEY", "")

    from crashcase.config import get_settings
    from crashcase.pipeline import retrieval
    from crashcase.pipeline.run import get_pipeline

    get_settings.cache_clear()
    get_pipeline.cache_clear()
    retrieval._memory_index = retrieval.InMemoryIndex()
    yield get_settings()
    get_settings.cache_clear()
    get_pipeline.cache_clear()
