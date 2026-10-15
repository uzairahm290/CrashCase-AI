import httpx

from crashcase.pipeline import report
from crashcase.schemas import DamageAssessment, Detection, FraudCheck, SimilarClaim


def _assessment():
    det = Detection(damage_type="dent", part="door", confidence=0.9, bbox=[0, 0, 5, 5], severity=0.2)
    sim = SimilarClaim(
        claim_ref="PC-aaaaaaaa",
        damage_type="dent",
        part="door",
        car_category="sedan",
        severity=0.2,
        cost_pkr=20000,
        similarity=0.9,
    )
    return DamageAssessment(
        detection=det,
        image="a.jpg",
        similar_claims=[sim],
        cost_low_pkr=18000,
        cost_high_pkr=22000,
        cost_estimate_pkr=20000,
        action="repair",
        basis="retrieval",
    )


def _fake_llm(monkeypatch, text):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 9}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())


def test_llm_report_used_when_citations_are_real(settings, monkeypatch):
    settings.llm_api_key = "test"
    _fake_llm(monkeypatch, "Dent on door, repair, PKR 18,000 to 22,000 (based on PC-aaaaaaaa).")
    text, gen = report.write_report(
        "sedan", [_assessment()], FraudCheck(flagged=False), 18000, 22000, settings
    )
    assert gen == "llm:llama-3.1-8b-instant" and "PC-aaaaaaaa" in text


def test_invented_citation_falls_back_to_template(settings, monkeypatch):
    settings.llm_api_key = "test"
    _fake_llm(monkeypatch, "Based on PC-aaaaaaaa and PC-deadbeef the cost is high.")
    text, gen = report.write_report(
        "sedan", [_assessment()], FraudCheck(flagged=False), 18000, 22000, settings
    )
    assert gen == "template:unfaithful-llm" and "PC-deadbeef" not in text


def test_llm_failure_and_none_key_use_template(settings, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    settings.llm_api_key = "test"
    assert (
        report.write_report("sedan", [_assessment()], FraudCheck(flagged=False), 1, 2, settings)[1]
        == "template"
    )
    settings.llm_api_key = "none"
    assert (
        report.write_report("sedan", [_assessment()], FraudCheck(flagged=False), 1, 2, settings)[1]
        == "template"
    )
