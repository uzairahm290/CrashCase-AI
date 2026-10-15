from conftest import make_image, to_bytes
from fastapi.testclient import TestClient

from crashcase.labeling import export_tasks, import_annotations, to_yolo_lines


def test_round_trip(settings, tmp_path):
    from crashcase.api.main import app
    from crashcase.db import get_sessionmaker
    from crashcase.storage import get_storage

    with TestClient(app) as c:
        files = [("files", ("a.jpg", to_bytes(make_image(9, size=(400, 200))), "image/jpeg"))]
        cid = c.post("/claims", files=files, data={"car_category": "sedan"}).json()["claim_id"]
        c.post(f"/claims/{cid}/review", json={"approved": True})

    storage = get_storage(settings)
    with get_sessionmaker(settings)() as session:
        tasks = export_tasks(session, storage, "http://x/{claim_id}/{name}")
    assert len(tasks) == 1
    box = tasks[0]["predictions"][0]["result"][0]
    # Stub box spans the middle half of the image: 25% -> 75%
    assert box["value"]["x"] == 25 and box["value"]["width"] == 50

    # Pretend a labeller kept the box and added a polygon
    poly = {
        "type": "polygonlabels",
        "value": {"points": [[10, 10], [20, 10], [20, 30]], "polygonlabels": ["crack"]},
    }
    tasks[0]["annotations"] = [{"result": [box, poly]}]
    assert import_annotations(tasks, storage, tmp_path / "fb") == 1
    [label] = list((tmp_path / "fb" / "labels").glob("*.txt"))
    lines = label.read_text().splitlines()
    assert lines[1] == "2 0.100000 0.100000 0.200000 0.100000 0.200000 0.300000"
    assert len(lines[0].split()) == 9  # class + 4 corner points
    assert (tmp_path / "fb" / "images" / f"{label.stem}.jpg").exists()


def test_unknown_labels_are_skipped():
    res = {
        "type": "rectanglelabels",
        "value": {"x": 0, "y": 0, "width": 1, "height": 1, "rectanglelabels": ["bird"]},
    }
    assert to_yolo_lines([res]) == []
