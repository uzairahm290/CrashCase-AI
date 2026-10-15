"""Label Studio round trip.

# 1. Approved claims -> tasks with the model's boxes as pre-annotations
python scripts/label_studio.py export --image-url "http://localhost:3000/api/claims/{claim_id}/images/{name}"
#    import label_studio_tasks.json in Label Studio (project config: configs/label_studio.xml),
#    or push straight to a project:
python scripts/label_studio.py export --ls-url http://localhost:8080 --ls-token $TOKEN --project 1

# 2. After labelling: Label Studio JSON export -> YOLO-seg data, versioned with DVC
python scripts/label_studio.py import project-1-export.json --out datasets/feedback
dvc add datasets/feedback && git add datasets/feedback.dvc
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from crashcase.config import get_settings
from crashcase.db import get_sessionmaker
from crashcase.labeling import export_tasks, import_annotations
from crashcase.storage import get_storage


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--image-url", default="http://localhost:3000/api/claims/{claim_id}/images/{name}")
    e.add_argument("--out", default="label_studio_tasks.json")
    e.add_argument("--ls-url")
    e.add_argument("--ls-token")
    e.add_argument("--project", type=int)
    i = sub.add_parser("import")
    i.add_argument("export_json")
    i.add_argument("--out", default="datasets/feedback")
    args = p.parse_args()

    s = get_settings()
    storage = get_storage(s)
    if args.cmd == "export":
        with get_sessionmaker(s)() as session:
            tasks = export_tasks(session, storage, args.image_url)
        Path(args.out).write_text(json.dumps(tasks, indent=2))
        print(f"wrote {len(tasks)} tasks to {args.out}")
        if args.ls_url and args.ls_token and args.project:
            r = httpx.post(
                f"{args.ls_url}/api/projects/{args.project}/import",
                headers={"Authorization": f"Token {args.ls_token}"},
                json=tasks,
                timeout=60,
            )
            r.raise_for_status()
            print(f"imported into Label Studio project {args.project}: {r.json()}")
    else:
        export = json.loads(Path(args.export_json).read_text())
        n = import_annotations(export, storage, Path(args.out))
        print(f"wrote {n} labelled images to {args.out}")


if __name__ == "__main__":
    main()
