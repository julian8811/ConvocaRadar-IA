"""Mock-based fixtures for testing source connectors.

Provides ready-made fixture data per connector group plus a factory
fixture that patches ``common.fetch_httpx_text``, ``common.fetch_httpx_bytes``,
and ``common.render_page_html`` so tests can drive connectors without
real network calls.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


# ── Helper: generate a minimal PDF with searchable text ───────────────────


def _make_sample_pdf() -> bytes:
    """Return a 1-page PDF that contains the text 'Research Grant 2027'."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 700, "Open Call for Research Grant 2027")
    c.drawString(72, 680, "Funding amount: USD 50,000")
    c.drawString(72, 660, "Closing date: 2027-06-30")
    c.save()
    buf.seek(0)
    return buf.getvalue()


# ── Fixture data per connector group ─────────────────────────────────────
# Each entry has:
#   "sample":  (final_url, content_or_bytes, content_type)
#   "empty":   same shape but empty/zero items
#   "garbage": malformed content that should degrade gracefully

FIXTURE_DATA: dict[str, dict[str, Any]] = {
    # 1. Standard GET, HTML response
    "httpx-get-html": {
        "sample": (
            "https://www.un.org/democracyfund/en/apply-for-funding",
            '<html><body><a href="/grant">Sample Grant</a></body></html>',
            "text/html",
        ),
        "empty": ("", "", "text/html"),
        "garbage": ("", "not useful content at all", "text/html"),
    },
    # 2. POST request, JSON response (EU-search API style)
    "httpx-post-json": {
        "sample": (
            "http://api.example.com/search",
            '{"results": [{"id": "123", "metadata": {"callTitle": ["Call X"], "identifier": ["ID-X"], "callIdentifier": ["CALL-X"], "status": ["31094501"], "actions": [{"deadlineDates": ["2027-06-30T00:00:00Z"]}]}}]}',
            "application/json",
        ),
        "empty": ("", '{"results": []}', "application/json"),
        "garbage": ("", "{{{broken}}}", "application/json"),
    },
    # 3. GET request, JSON response (Atom-feed style for GenericHtmlConnector)
    "httpx-get-json": {
        "sample": (
            "http://api.example.com/feed",
            '{"feed": {"entry": [{"title": "NSF Grant", "url": "http://example.com/nsf-123"}]}}',
            "application/json",
        ),
        "empty": ("", "{}", "application/json"),
        "garbage": ("", "not json at all", "application/json"),
    },
    # 4. GET request, RSS/XML response
    "httpx-get-rss": {
        "sample": (
            "http://example.com/feed.rss",
            '<rss version="2.0"><channel><item><title>Grant</title><link>http://example.com/1</link></item></channel></rss>',
            "application/rss+xml",
        ),
        "empty": (
            "",
            "<rss version='2.0'><channel></channel></rss>",
            "application/rss+xml",
        ),
        "garbage": (
            "",
            "<rss>corrupt</rss>",
            "application/rss+xml",
        ),
    },
    # 5. GET request, PDF binary response
    "httpx-get-pdf": {
        "sample": (
            "http://example.com/grant.pdf",
            _make_sample_pdf(),
            "application/pdf",
        ),
        "empty": ("", b"", "application/pdf"),
        "garbage": ("", b"this is not a pdf", "application/pdf"),
    },
    # 6. Playwright (JS-rendered HTML) — same HTML as group 1
    "playwright": {
        "sample": (
            "http://innovamos.gov.co/convocatorias",
            '<html><body><a href="/grant">Sample Grant</a></body></html>',
            "text/html",
        ),
        "empty": ("", "", "text/html"),
        "garbage": ("", "not useful content at all", "text/html"),
    },
    # 7. Hybrid connector — starts with RSS content, delegates to RssConnector
    "hybrid": {
        "sample": (
            "http://example.com/feed.rss",
            '<rss version="2.0"><channel><item><title>Hybrid Grant</title><link>http://example.com/hybrid</link></item></channel></rss>',
            "application/rss+xml",
        ),
        "empty": (
            "",
            "<rss version='2.0'><channel></channel></rss>",
            "application/rss+xml",
        ),
        "garbage": ("", "<rss>corrupt</rss>", "application/rss+xml"),
    },
    # 8. Generic API (source_type="api") — flat JSON array
    "generic-api": {
        "sample": (
            "http://api.example.com/grants",
            '[{"title": "API Grant", "url": "http://example.com/1"}]',
            "application/json",
        ),
        "empty": ("", "[]", "application/json"),
        "garbage": ("", "{{{not json}}}", "application/json"),
    },
    # 9. Grants.gov POST style (POST with JSON payload, grants.gov JSON shape)
    "grants-gov": {
        "sample": (
            "http://api.grants.gov/v1/api/search2",
            '{"data": {"oppHits": [{"id": "GRA-123", "title": "Federal Research Grant", "agencyName": "NSF", "openDate": "01/01/2027", "closeDate": "07/01/2027"}]}}',
            "application/json",
        ),
        "empty": ('', '{}', "application/json"),
        "garbage": ('', '{{{not json}}}', "application/json"),
    },
}


# ── Fixture data for network-error scenario ──────────────────────────────

NETWORK_ERROR_MSG = "simulated network error"


# ── Factory fixture moved to conftest.py ─────────────────────────────────👍


# ── Helper: apply fixture data to the correct mock ───────────────────────


def apply_fixture_data(
    mocks: dict[str, AsyncMock],
    fixture_key: str,
    scenario: str = "sample",
    *,
    side_effect: Any = None,
) -> None:
    """Configure the appropriate mock based on the connector group.

    Sets ``side_effect`` or ``return_value`` on the relevant mock so the
    connector's ``fetch()`` receives the fixture data.

    Parameters
    ----------
    mocks:
        The ``{mock_name: AsyncMock}`` dict returned by ``connector_factory``.
    fixture_key:
        Key into ``FIXTURE_DATA`` (e.g. ``"httpx-get-html"``).
    scenario:
        ``"sample"``, ``"empty"``, or ``"garbage"``.
    side_effect:
        If given, set as the mock's side_effect (overrides scenario data).
    """
    if side_effect is not None:
        # Apply to all mocks so whichever one is called gets the error
        for mock in mocks.values():
            mock.side_effect = side_effect
        return

    data = FIXTURE_DATA[fixture_key][scenario]
    _url, content, content_type = data

    # Determine which mock to configure based on fixture_key
    if fixture_key == "httpx-get-pdf":
        mocks["fetch_httpx_bytes"].return_value = data
    elif fixture_key == "playwright":
        # Playwright connectors first try fetch_httpx_text with fallback,
        # then fall back to render_page_html. We make fetch_httpx_text
        # raise so that render_page_html is called instead.
        mocks["fetch_httpx_text"].side_effect = RuntimeError("httpx failed, fallback to playwright")
        mocks["render_page_html"].return_value = data
    else:
        mocks["fetch_httpx_text"].return_value = data
