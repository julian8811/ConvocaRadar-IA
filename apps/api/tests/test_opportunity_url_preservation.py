"""Regression tests for prior URL preservation during duplicate ingestion.

The network reachability check is upstream of this function. Failed checks
send None, which must not erase a previously retained opportunity URL.
"""
from types import SimpleNamespace

import app.services.opportunity as service


def _sample(**overrides):
    base = dict(
        title="Convocatoria académica",
        entity="Universidad",
        country="Colombia",
        region=None,
        language="es",
        categories=[],
        topics=[],
        description="Contenido verificado previamente",
        summary="Convocatoria académica oficial con requisitos y condiciones",
        raw_text="",
        official_url=None,
        application_url=None,
        funding_amount_value=None,
        funding_amount_currency=None,
        funding_amount_raw=None,
        open_date=None,
        close_date=None,
        eligible_applicants=[],
        requirements=[],
        documents_required=[],
        evaluation_criteria=[],
        restrictions=[],
        risk_flags=[],
        confidence_score=0.5,
        status="unknown",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_failed_validation_cannot_erase_previously_stored_links(monkeypatch):
    monkeypatch.setattr(service, "inferred_opportunity_status", lambda *_: "unknown")
    existing = _sample(
        official_url="https://ascun.org.co/convocatoria-previa/",
        application_url="https://ascun.org.co/postular/",
    )
    candidate = _sample(official_url=None, application_url=None)
    service._update_opportunity(existing, candidate, candidate.title)
    assert existing.official_url == "https://ascun.org.co/convocatoria-previa/"
    assert existing.application_url == "https://ascun.org.co/postular/"


def test_verified_new_link_can_replace_previous_link(monkeypatch):
    monkeypatch.setattr(service, "inferred_opportunity_status", lambda *_: "unknown")
    existing = _sample(official_url="https://ascun.org.co/convocatoria-previa/")
    candidate = _sample(official_url="https://ascun.org.co/convocatoria-actual/")
    service._update_opportunity(existing, candidate, candidate.title)
    assert existing.official_url == "https://ascun.org.co/convocatoria-actual/"


def test_missing_links_remain_missing_when_no_previous_link(monkeypatch):
    monkeypatch.setattr(service, "inferred_opportunity_status", lambda *_: "unknown")
    existing = _sample(official_url=None, application_url=None)
    candidate = _sample(official_url=None, application_url=None)
    service._update_opportunity(existing, candidate, candidate.title)
    assert existing.official_url is None
    assert existing.application_url is None
