import io

import numpy as np
from conftest import make_image, to_bytes
from PIL import Image

from crashcase.pipeline import costing, fraud
from crashcase.pipeline.embedder import HistogramEmbedder
from crashcase.pipeline.quality import check_quality
from crashcase.pipeline.retrieval import InMemoryIndex, PastClaim
from crashcase.schemas import Detection, SimilarClaim


def test_quality_gate(settings):
    assert check_quality("ok.jpg", make_image(), settings).passed
    blurry = check_quality("b.jpg", make_image(blur=True), settings)
    assert not blurry.passed and "blurry" in blurry.reason
    dark = check_quality("d.jpg", make_image(brightness=0.15), settings)
    assert not dark.passed and "dark" in dark.reason


def test_dhash_detects_reused_photo():
    a, b = make_image(1), make_image(2)
    ha, hb = fraud.dhash(a), fraud.dhash(b)
    resaved = Image.open(io.BytesIO(to_bytes(a.resize((300, 225)))))
    assert len(ha) == 64
    assert fraud.hamming(ha, fraud.dhash(resaved)) <= 18
    assert fraud.hamming(ha, hb) > 60
    assert fraud.find_duplicates([fraud.dhash(resaved)], [("old-claim", ha)], 18) == [
        ("old-claim", fraud.hamming(ha, fraud.dhash(resaved)))
    ]


def test_edited_photo_flag():
    exif = Image.Exif()
    exif[0x0131] = "Adobe Photoshop 25.0"
    img = Image.open(io.BytesIO(to_bytes(make_image(), exif=exif)))
    assert fraud.edited_with(img) == "photoshop"
    assert fraud.edited_with(make_image()) is None


def test_cost_table_rules(settings):
    table = costing.load_cost_table(settings.cost_table_path)
    assert table.action("glass_shatter", 0.1) == "replace"
    assert table.action("scratch", 0.1) == "repair"
    assert table.action("dent", 0.6) == "replace"
    small = table.base_cost("dent", "door", 0.1, "sedan")
    big = table.base_cost("dent", "door", 0.4, "sedan")
    assert small < big
    assert table.base_cost("dent", "door", 0.3, "suv") > table.base_cost("dent", "door", 0.3, "hatchback")


def test_estimate_uses_retrieval_then_falls_back(settings):
    table = costing.load_cost_table(settings.cost_table_path)
    det = Detection(damage_type="dent", part="door", confidence=0.9, bbox=[0, 0, 10, 10], severity=0.2)
    similar = [
        SimilarClaim(
            claim_ref=f"PC-{i}",
            damage_type="dent",
            part="door",
            car_category="sedan",
            severity=0.2,
            cost_pkr=cost,
            similarity=0.9,
        )
        for i, cost in enumerate([20000, 22000, 24000])
    ]
    est, low, high, basis = costing.estimate(det, "sedan", similar, table)
    assert basis == "retrieval" and low < est < high and 20000 <= est <= 24000

    est, low, high, basis = costing.estimate(det, "sedan", [], table)
    assert basis == "cost_table" and low < est < high

    # A replace-level dent must not be priced like the cheap repairs it was matched with.
    severe = det.model_copy(update={"severity": 0.6})
    est_severe, *_ = costing.estimate(severe, "sedan", similar, table)
    replace_price = table.base_cost("dent", "door", 0.6, "sedan")
    assert est_severe > 2 * 22000 and abs(est_severe - replace_price) / replace_price < 0.3


def test_index_filters_and_ranks():
    emb = HistogramEmbedder()
    q = emb.embed(make_image(5))
    idx = InMemoryIndex()
    near = PastClaim("dent", "door", "sedan", 0.2, 20000, q.copy())
    far = PastClaim("dent", "door", "sedan", 0.2, 90000, emb.embed(make_image(6, brightness=0.3)))
    other = PastClaim("scratch", "door", "sedan", 0.2, 5000, q.copy())
    idx.add([far, near, other])

    res = idx.search(q, "dent", "sedan", "door", k=2)
    assert [r.claim_ref for r in res] == [near.ref, far.ref]
    assert np.isclose(res[0].similarity, 1.0, atol=1e-3)
    assert idx.search(q, "dent", "suv", "door", k=2) == []
