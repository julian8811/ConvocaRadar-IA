"""Regression coverage for ASCUN routing, editorial triage and WP title discovery."""

from __future__ import annotations

import json

import pytest

from app.connectors.ascun import (
    AscunConnector, _title_decision,
)
from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.factory import connector_for
from app.connectors.wordpress_grants import WordPressGrantsConnector


def test_factory_routes_ascun_before_wordpress_url_heuristic():
    assert isinstance(
        connector_for(
            "ascun-convocatorias",
            "https://ascun.org.co/wp-json/wp/v2/posts",
            "api",
        ),
        AscunConnector,
    )


def test_factory_preserves_novo_and_generic_wordpress_routes():
    assert isinstance(
        connector_for(
            "novo-nordisk-grants",
            "https://novonordiskfonden.dk/wp-json/wp/v2/grant",
            "api",
        ),
        WordPressGrantsConnector,
    )
    assert isinstance(
        connector_for(
            "unrelated-wp-source",
            "https://example.org/wp-json/wp/v2/posts",
            "api",
        ),
        WordPressGrantsConnector,
    )


@pytest.mark.asyncio
async def test_parse_and_validate_real_world_title_cases():
    cases = [
        ("Totto abre convocatoria nacional para estudiantes", True),
        ("Más plazo para inscribirse al Premio de Innovación INNPACTA 2026", True),
        ("Abierta la convocatoria a las Becas CAPES de movilidad", True),
        ("Inscríbete a la Beca Alberto Assa para futuros licenciados", True),
        ("Escuela de Verano ofrece 20 becas para explorar el Caribe", True),
        ("Convocatoria profesoral UIS 2026: mañana vence el plazo", False),
        ("Convocatoria abierta para mentores voluntarios de Sinapsis Nitro", False),
        ("Convocatoria pública para veedores ciudadanos", False),
        ("Cuatro proyectos seleccionados en la convocatoria nacional Orquídeas 2025", False),
        ("Anunciamos la selección del proyecto GLOSOUTH en la convocatoria ICETEX 2024", False),
        ("Instituciones colombianas se preparan para las convocatorias Horizon Europe", False),
        ("Músico de la UNAL se llevó todos los premios del Concurso WASBE", False),
        ("Estudiantes ganan premio de periodismo La Bagatela", False),
        ("Beca Fulbright para doctoranda de Univalle", False),
        ("Fondo para la Vida destaca proyecto de UNIMAGDALENA", False),
        ("La UNAL da inicio a la Cátedra Nacional de Paz", False),
    ]
    payload = [
        {
            "title": {"rendered": title},
            "link": f"https://ascun.org.co/noticias-ies/nota-{i}/",
            "date": "2026-09-23T09:00:00",
            "excerpt": {"rendered": "<p>Resumen editorial universitario.</p>"},
            "content": {"rendered": "<p>Contenido de artículo.</p>"},
        }
        for i, (title, _) in enumerate(cases)
    ]
    connector = AscunConnector()
    candidates = await connector.parse(
        RawSourceResult(
            source_key="ascun-convocatorias",
            url="https://ascun.org.co/wp-json/wp/v2/posts",
            content=json.dumps(payload),
            content_type="application/json",
        )
    )
    assert len(candidates) == len(cases)
    assert [
        (await connector.validate(candidate)).ok
        for candidate in candidates
    ] == [expected for _, expected in cases]
    assert all(candidate.open_date is None for candidate in candidates)
    assert all(candidate.close_date is None for candidate in candidates)
    assert "<p>" not in candidates[0].summary
    assert candidates[3].categories == ["convocatorias", "becas", "educacion"]
    assert candidates[1].categories == ["convocatorias", "premios", "educacion"]


@pytest.mark.asyncio
async def test_validate_rejects_domain_spoofing():
    candidate = OpportunityCandidate(
        title="Abre convocatoria de innovación",
        entity="ASCUN Colombia",
        country="Colombia",
        official_url="https://ascun.org.co.evil.example/convocatoria/",
    )
    assert not (await AscunConnector().validate(candidate)).ok



@pytest.mark.asyncio
async def test_explicitly_expired_close_date_is_not_actionable():
    from datetime import datetime

    candidate = OpportunityCandidate(
        title="Abierta la convocatoria a las Becas CAPES para movilidad",
        entity="ASCUN Colombia",
        country="Colombia",
        official_url="https://ascun.org.co/noticias-ies/becas-capes/",
        close_date=datetime(2024, 8, 8),
    )
    validation = await AscunConnector().validate(candidate)
    assert not validation.ok
    assert "past" in validation.reason.lower()

def test_unknown_scholarship_headline_is_not_assumed_open():
    accepted, reason = _title_decision("Beca Hospital Universidad del Norte")
    assert not accepted
    assert "review" in reason.lower()


@pytest.mark.asyncio
async def test_fetch_uses_bounded_pagination_title_search_dedup_and_relevance(monkeypatch):
    import app.connectors.ascun as module

    requests = []
    common = {
        "title": {"rendered": "Cuatro proyectos seleccionados en convocatoria Orquídeas"},
        "link": "https://ascun.org.co/noticias-ies/resultado/",
        "date": "2026-10-12T08:00:00",
        "excerpt": {"rendered": "<p>Concluyó.</p>"},
    }
    call = {
        "title": {"rendered": "Inscríbete a la Beca Alberto Assa"},
        "link": "https://ascun.org.co/noticias-ies/inscripcion/",
        "date": "2026-10-01T08:00:00",
        "excerpt": {"rendered": "<p>Postúlate.</p>"},
    }
    news = {
        "title": {"rendered": "Informe anual de educación"},
        "link": "https://ascun.org.co/noticias-ies/informe/",
        "date": "2026-09-29T08:00:00",
        "excerpt": {"rendered": "<p>Informe.</p>"},
    }

    class FakeResponse:
        def __init__(self, data, pages):
            self._data = data
            self.headers = {"X-WP-TotalPages": str(pages)}

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeClient:
        async def get(self, base_url, *, params, **kwargs):
            query = params["search"]
            number = params["page"]
            requests.append((base_url, query, number, params.copy(), kwargs))
            if query == "convocatoria":
                return FakeResponse([common] if number == 1 else [call], 2)
            return FakeResponse([common, news], 1)

    async def fake_http_client():
        return FakeClient()

    monkeypatch.setattr(module, "TITLE_QUERIES", ("convocatoria", "beca"))
    monkeypatch.setattr(module, "http_client", fake_http_client)
    raw = await AscunConnector().fetch()
    ordered = json.loads(raw.content)

    assert raw.metadata["searches_ok"] == 2
    assert raw.metadata["unique_posts"] == 3
    assert len(ordered) == 3
    assert ordered[0]["link"] == call["link"]
    assert sorted((q, n) for _, q, n, _, _ in requests) == [
        ("beca", 1),
        ("convocatoria", 1),
        ("convocatoria", 2),
    ]
    assert all(
        p["search_columns[]"] == "post_title"
        and p["per_page"] == 30
        for _, _, _, p, _ in requests
    )
    assert all(kw["timeout"] == 15.0 for *_, kw in requests)
