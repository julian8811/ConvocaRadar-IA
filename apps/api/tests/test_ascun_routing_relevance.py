"""ASCUN must use a purpose-built news/calls triage, not Novo's grants parser."""

from __future__ import annotations

import json

import pytest

from app.connectors.ascun import AscunConnector
from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.factory import connector_for
from app.connectors.wordpress_grants import WordPressGrantsConnector


def test_factory_routes_ascun_before_wordpress_url_heuristic():
    result = connector_for(
        "ascun-convocatorias",
        "https://ascun.org.co/wp-json/wp/v2/posts",
        "api",
    )
    assert isinstance(result, AscunConnector)


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
            "an-unrelated-wp-source",
            "https://example.org/wp-json/wp/v2/posts",
            "api",
        ),
        WordPressGrantsConnector,
    )


@pytest.mark.asyncio
async def test_parse_and_validate_distinguish_calls_from_news():
    titles = [
        "Totto abre convocatoria nacional para estudiantes de Colombia",
        "Más plazo para inscribirse al premio de innovación INNPACTA 2026",
        "Convocatoria profesoral UIS 2026: mañana vence el plazo",
        "Estudiantes ganan premio de periodismo La Bagatela",
        "Beca Fulbright para doctoranda de Univalle",
        "Fondo para la Vida destaca proyecto de UNIMAGDALENA",
        "La UNAL da inicio a la Cátedra Nacional de Paz",
    ]
    payload = [
        {
            "title": {"rendered": title},
            "link": f"https://ascun.org.co/noticias-ies/nota-{i}/",
            "date": "2026-09-23T09:00:00",
            "excerpt": {"rendered": "<p>Resumen de noticia universitaria.</p>"},
            "content": {"rendered": "<p>Artículo completo de ASCUN.</p>"},
        }
        for i, title in enumerate(titles)
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
    assert len(candidates) == len(titles)
    outcome = [(await connector.validate(candidate)).ok for candidate in candidates]
    assert outcome == [True, True, False, False, False, False, False]

    # Publication date is not a claim that an application window opened.
    assert all(candidate.open_date is None for candidate in candidates)
    assert all(candidate.close_date is None for candidate in candidates)
    assert candidates[0].categories == ["convocatorias", "educacion"]
    assert candidates[1].categories == ["convocatorias", "premios", "educacion"]
    assert "Artículo completo" in candidates[0].raw_text


@pytest.mark.asyncio
async def test_validate_rejects_domain_spoofing():
    connector = AscunConnector()
    candidate = OpportunityCandidate(
        title="Abre convocatoria de innovación",
        entity="ASCUN Colombia",
        country="Colombia",
        official_url="https://ascun.org.co.evil.example/convocatoria/",
    )
    assert not (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_fetch_uses_bounded_wordpress_search(monkeypatch):
    import app.connectors.ascun as module

    seen = []

    async def fake_fetch(url, **kwargs):
        seen.append((url, kwargs))
        return (url, "[]", "application/json")

    monkeypatch.setattr(module, "fetch_httpx_text", fake_fetch)
    result = await AscunConnector().fetch()
    assert result.content == "[]"
    assert len(seen) == 1
    assert "search=convocatoria" in seen[0][0]
    assert "per_page=20" in seen[0][0]
    assert seen[0][1]["playwright_fallback"] is False
