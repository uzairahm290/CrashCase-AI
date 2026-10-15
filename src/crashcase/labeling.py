"""Label Studio round trip: approved claims out as pre-labelled tasks, corrected labels back in
as YOLOv8-seg training data (datasets/feedback), ready for `dvc add` and the retrain flow."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from crashcase.db import Claim
from crashcase.schemas import DAMAGE_TYPES
from crashcase.storage import Storage


def export_tasks(session, storage: Storage, image_url: str, statuses=("approved",)) -> list[dict]:
    """One task per photo, with the model's detections as editable pre-annotations.

    `image_url` is a template like "https://app/api/claims/{claim_id}/images/{name}".
    """
    tasks = []
    claims = session.scalars(select(Claim).where(Claim.status.in_(statuses)))
    for c in claims:
        r = c.result or {}
        for key in c.image_keys or []:
            name = key.split("/", 1)[1]
            w, h = Image.open(io.BytesIO(storage.load(key))).size
            boxes = [a["detection"] for a in r.get("assessments", []) if a["image"] == name]
            results = [
                {
                    "id": f"{c.id[:8]}-{i}",
                    "from_name": "damage_box",
                    "to_name": "image",
                    "type": "rectanglelabels",
                    "original_width": w,
                    "original_height": h,
                    "value": {
                        "x": d["bbox"][0] / w * 100,
                        "y": d["bbox"][1] / h * 100,
                        "width": (d["bbox"][2] - d["bbox"][0]) / w * 100,
                        "height": (d["bbox"][3] - d["bbox"][1]) / h * 100,
                        "rectanglelabels": [d["damage_type"]],
                    },
                    "score": d["confidence"],
                }
                for i, d in enumerate(boxes)
            ]
            tasks.append(
                {
                    "data": {
                        "image": image_url.format(claim_id=c.id, name=name),
                        "claim_id": c.id,
                        "storage_key": key,
                    },
                    "predictions": [
                        {
                            "model_version": (r.get("model_versions") or {}).get("detector", ""),
                            "result": results,
                        }
                    ],
                }
            )
    return tasks


def to_yolo_lines(annotation_results: list[dict]) -> list[str]:
    """Label Studio results (percent coords) -> YOLOv8-seg lines (class + normalised polygon)."""
    lines = []
    for res in annotation_results:
        v = res["value"]
        if res["type"] == "polygonlabels":
            label, points = v["polygonlabels"][0], v["points"]
        elif res["type"] == "rectanglelabels":
            label = v["rectanglelabels"][0]
            x, y, w, h = v["x"], v["y"], v["width"], v["height"]
            points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        else:
            continue
        if label not in DAMAGE_TYPES:
            continue
        coords = " ".join(f"{p / 100:.6f}" for pt in points for p in pt)
        lines.append(f"{DAMAGE_TYPES.index(label)} {coords}")
    return lines


def import_annotations(export: list[dict], storage: Storage, out: Path) -> int:
    """Write images + labels for every task that has a human annotation."""
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    written = 0
    for task in export:
        anns = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
        if not anns:
            continue
        key = task["data"]["storage_key"]
        stem = key.replace("/", "__").rsplit(".", 1)[0]
        (out / "images" / f"{stem}.jpg").write_bytes(storage.load(key))
        (out / "labels" / f"{stem}.txt").write_text("\n".join(to_yolo_lines(anns[-1]["result"])))
        written += 1
    (out / "data.yaml").write_text(
        json.dumps(
            {
                "path": str(out.resolve()),
                "train": "images",
                "val": "images",
                "names": dict(enumerate(DAMAGE_TYPES)),
            },
            indent=2,
        )
    )
    return written
