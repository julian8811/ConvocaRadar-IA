"""Ascun fetch-base bound: el TimeoutError de 90s ocurrio en el listado WP.

El path vivo es WordPressGrantsConnector (factory rutea cualquier
base_url /wp-json/wp/v2/ ahi, opacando a AscunConnector). Pre-b5cada1 el
fetch hacia hasta 10 paginas secuenciales x 15s = 150s > budget 90s.
Cero network: http_client mockeado.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ASCUN_BASE_URL = "https://ascun.org.co/wp-json/wp/v2/posts"


def _page(items, total_pages="9", page=1):
    resp = AsyncMock()
    resp.json = MagicMock(return_value=items)
    resp.headers = {"X-WP-TotalPages": total_pages}
    resp.raise_for_status = MagicMock()
    resp.url = f"{ASCUN_BASE_URL}?page={page}"
    return resp


def _item(i):
    return {"id": i, "title": {"rendered": f"Noticia {i}"}, "link": f"https://ascun.org.co/n{i}"}


async def _run_fetch(connector, side_effect):
    with patch(
        "app.connectors.wordpress_grants.http_client", new_callable=AsyncMock
    ) as mock_http_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=side_effect)
        mock_http_client.return_value = mock_client
        result = await connector.fetch()
    return mock_client, result


def _ascun_connector():
    from app.connectors.factory import connector_for

    return connector_for("ascun-convocatorias", ASCUN_BASE_URL, "api")


def test_factory_routes_ascun_to_wordpress_capped():
    """El seed usa la URL WP JSON: factory debe devolver WP capado, no AscunConnector."""
    connector = _ascun_connector()
    assert connector.__class__.__name__ == "WordPressGrantsConnector"
    assert connector.max_pages == 3


async def test_fetch_base_makes_at_most_3_requests():
    """TotalPages=9 (~9 paginas x100 en prod) -> exactamente 3 requests, no 9."""
    connector = _ascun_connector()
    pages = [_page([_item(p)], total_pages="9", page=p) for p in range(1, 10)]
    mock_client, result = await _run_fetch(connector, pages)
    assert mock_client.get.await_count == 3
    assert result.metadata["items_fetched"] == 3


async def test_per_request_timeout_is_granular():
    """Cada pagina lleva timeout propio <=15s, no el global de 180s."""
    connector = _ascun_connector()
    pages = [_page([_item(p)], total_pages="9", page=p) for p in range(1, 10)]
    mock_client, _ = await _run_fetch(connector, pages)
    # NB: await_calls queda vacio con side_effect iterable (CPython);
    # mock_calls si registra cada GET con sus kwargs.
    for call in mock_client.get.mock_calls:
        assert call.kwargs["timeout"] <= 15


async def test_worst_case_bound_fits_90s_budget():
    """Invariante de la incidencia: max_pages x timeout_pagina <= 90s."""
    connector = _ascun_connector()
    pages = [_page([_item(p)], total_pages="9", page=p) for p in range(1, 10)]
    mock_client, _ = await _run_fetch(connector, pages)
    observed_timeout = max(c.kwargs["timeout"] for c in mock_client.get.mock_calls)
    assert connector.max_pages * observed_timeout <= 90


async def test_failed_page_breaks_with_partial_without_raising():
    """El fetch nunca revienta el budget: pagina 2 falla -> parcial, sin raise."""
    connector = _ascun_connector()
    mock_client, result = await _run_fetch(
        connector, [_page([_item(1)], total_pages="9", page=1), RuntimeError("slow")]
    )
    assert mock_client.get.await_count == 2
    assert result.metadata["items_fetched"] == 1


async def test_pages_fetched_reports_actual_pages():
    """RED: con TotalPages=9 y fallo en pagina 2, pages_fetched debe ser 1 real."""
    connector = _ascun_connector()
    _, result = await _run_fetch(
        connector, [_page([_item(1)], total_pages="9", page=1), RuntimeError("slow")]
    )
    assert result.metadata["pages_fetched"] == 1
