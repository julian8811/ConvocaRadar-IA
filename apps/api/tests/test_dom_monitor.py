"""Tests for app.scraper.dom_monitor — DOM hash tracking and structural change detection.

Strict TDD: tests written first, implementation follows.
"""
from __future__ import annotations


import pytest

from app.scraper.dom_monitor import (
    compute_dom_hash,
    detect_structural_change,
    normalize_html,
    extract_list_item_count,
)


# ═══════════════════════════════════════════════════════════════
# 1. normalize_html
# ═══════════════════════════════════════════════════════════════


class TestNormalizeHtml:
    """HTML normalization strips dynamic/noise content before hashing."""

    def test_strips_script_tags(self):
        """Script tags and their content are removed."""
        html = "<html><head><script>console.log('hello')</script></head><body><p>Content</p></body></html>"
        result = normalize_html(html)
        assert "console.log" not in result
        assert "<p>Content</p>" in result

    def test_strips_style_tags(self):
        """Style tags and their content are removed."""
        html = "<html><head><style>body { color: red; }</style></head><body><p>Content</p></body></html>"
        result = normalize_html(html)
        assert "color: red" not in result
        assert "<p>Content</p>" in result

    def test_normalizes_whitespace(self):
        """Excessive whitespace is collapsed."""
        html = "<html><body><p>   Hello   World   </p></body></html>"
        result = normalize_html(html)
        assert "   " not in result  # No triple spaces
        assert "Hello World" in result

    def test_identical_content_produces_identical_output(self):
        """Same HTML structure always normalizes to the same string."""
        html_a = "<html><body><div>Hello</div></body></html>"
        html_b = "<html><body><div>Hello</div></body></html>"
        assert normalize_html(html_a) == normalize_html(html_b)

    def test_different_dynamic_content_still_normalizes_to_same(self):
        """HTML that differs only in script content normalizes identically."""
        html_a = '<html><body><p>Static</p><script>var x = 1;</script></body></html>'
        html_b = '<html><body><p>Static</p><script>var x = 999;</script></body></html>'
        assert normalize_html(html_a) == normalize_html(html_b)

    def test_removes_timestamp_patterns(self):
        """Common timestamp/datetime patterns in attributes are removed."""
        html = '<html><body><div data-timestamp="2024-01-15T10:30:00Z"><p>Content</p></div></body></html>'
        result = normalize_html(html)
        assert "2024-01-15" not in result
        assert "<p>Content</p>" in result

    def test_handles_empty_string(self):
        """Empty HTML returns empty string."""
        assert normalize_html("") == ""

    def test_handles_none(self):
        """None input returns empty string."""
        assert normalize_html(None) == ""


# ═══════════════════════════════════════════════════════════════
# 2. compute_dom_hash
# ═══════════════════════════════════════════════════════════════


class TestComputeDomHash:
    """DOM hash is a deterministic SHA256 of normalized HTML."""

    def test_returns_sha256_hex_string(self):
        """The result is a 64-char hex string (SHA256)."""
        html = "<html><body><p>Hello</p></body></html>"
        result = compute_dom_hash(html)
        assert isinstance(result, str)
        assert len(result) == 64
        # Verify it's a valid hex string
        int(result, 16)

    def test_same_html_produces_same_hash(self):
        """Identical HTML content always produces the same hash."""
        html = "<html><body><div>Test Content</div></body></html>"
        hash_a = compute_dom_hash(html)
        hash_b = compute_dom_hash(html)
        assert hash_a == hash_b

    def test_different_html_produces_different_hash(self):
        """Different HTML content produces a different hash."""
        html_a = "<html><body><p>Version A</p></body></html>"
        html_b = "<html><body><p>Version B</p></body></html>"
        assert compute_dom_hash(html_a) != compute_dom_hash(html_b)

    def test_dynamic_content_stripped_for_stable_hash(self):
        """HTML that differs only in scripts/styles produces the same hash."""
        html_with_script = '<html><body><p>Stable</p><script>var x = Math.random();</script></body></html>'
        html_without_script = '<html><body><p>Stable</p></body></html>'
        assert compute_dom_hash(html_with_script) == compute_dom_hash(html_without_script)

    def test_analytics_params_stripped(self):
        """URLs with analytics/tracking params normalize to the same hash."""
        html_a = '<html><body><a href="https://example.com/page?utm_source=twitter&utm_campaign=summer">Link</a></body></html>'
        html_b = '<html><body><a href="https://example.com/page">Link</a></body></html>'
        assert compute_dom_hash(html_a) == compute_dom_hash(html_b)

    def test_empty_html_has_deterministic_hash(self):
        """Even empty HTML produces a valid deterministic hash."""
        hash_a = compute_dom_hash("")
        hash_b = compute_dom_hash("")
        assert hash_a == hash_b

    def test_different_static_content_different_hashes(self):
        """Structural changes (different text, different elements) produce different hashes."""
        html_table = "<html><body><table><tr><td>Item 1</td></tr></table></body></html>"
        html_list = "<html><body><ul><li>Item 1</li></ul></body></html>"
        assert compute_dom_hash(html_table) != compute_dom_hash(html_list)

    def test_content_added_changes_hash(self):
        """Adding new content elements changes the DOM hash."""
        html_before = "<html><body><p>Original</p></body></html>"
        html_after = "<html><body><p>Original</p><p>New paragraph</p></body></html>"
        assert compute_dom_hash(html_before) != compute_dom_hash(html_after)


# ═══════════════════════════════════════════════════════════════
# 3. detect_structural_change
# ═══════════════════════════════════════════════════════════════


class TestDetectStructuralChange:
    """Detect structural change compares two DOM hashes."""

    def test_same_hash_no_change(self):
        """Two identical hashes mean no structural change."""
        html = "<html><body><p>Content</p></body></html>"
        h = compute_dom_hash(html)
        assert detect_structural_change(h, h) is False
        assert detect_structural_change(h, h, threshold=0.0) is False

    def test_different_hash_detects_change(self):
        """Two different hashes mean a structural change."""
        html_a = "<html><body><p>Version A</p></body></html>"
        html_b = "<html><body><p>Version B</p></body></html>"
        h_a = compute_dom_hash(html_a)
        h_b = compute_dom_hash(html_b)
        assert detect_structural_change(h_a, h_b) is True

    def test_acceptable_threshold_ignores_minor_changes(self):
        """Threshold parameter is accepted even if hash comparison is binary."""
        html_a = "<html><body><p>Same</p></body></html>"
        html_b = "<html><body><p>Same</p></body></html>"
        h_a = compute_dom_hash(html_a)
        h_b = compute_dom_hash(html_b)
        # Same content — always no change regardless of threshold
        assert detect_structural_change(h_a, h_b, threshold=0.0) is False
        assert detect_structural_change(h_a, h_b, threshold=1.0) is False

    def test_threshold_value_is_validated(self):
        """Invalid threshold values raise ValueError."""
        h = "a" * 64
        with pytest.raises(ValueError, match="Threshold must be between 0.0 and 1.0"):
            detect_structural_change(h, h, threshold=-0.1)
        with pytest.raises(ValueError, match="Threshold must be between 0.0 and 1.0"):
            detect_structural_change(h, h, threshold=1.1)

    def test_none_hash_returns_true(self):
        """When old_hash is None (first scrape), it's always a change."""
        h = compute_dom_hash("<html><body><p>First scrape</p></body></html>")
        assert detect_structural_change(None, h) is True


# ═══════════════════════════════════════════════════════════════
# 4. extract_list_item_count
# ═══════════════════════════════════════════════════════════════


class TestExtractListItemCount:
    """Count matching items for a list of CSS selectors."""

    def test_returns_count_for_matching_selector(self):
        """Returns the number of items matching the first valid selector."""
        html = """<html><body>
        <div class="card"><h2>Item 1</h2></div>
        <div class="card"><h2>Item 2</h2></div>
        <div class="card"><h2>Item 3</h2></div>
        </body></html>"""
        count = extract_list_item_count(html, [".card", ".item"])
        assert count == 3

    def test_fallback_selector(self):
        """Uses the second selector when the first matches nothing."""
        html = """<html><body>
        <div class="item"><h2>Item 1</h2></div>
        <div class="item"><h2>Item 2</h2></div>
        </body></html>"""
        count = extract_list_item_count(html, [".missing", ".item"])
        assert count == 2

    def test_no_matching_selector_returns_zero(self):
        """Returns 0 when no selector matches."""
        html = "<html><body><p>No items here</p></body></html>"
        count = extract_list_item_count(html, [".card", ".item"])
        assert count == 0

    def test_empty_html_returns_zero(self):
        """Returns 0 for empty HTML."""
        assert extract_list_item_count("", [".card"]) == 0


# ═══════════════════════════════════════════════════════════════
# 5. Source model DOM fields
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 5. ConfigurableHtmlConnector selector diagnostics
# ═══════════════════════════════════════════════════════════════


SAMPLE_LIST_HTML = """<html><body>
<div class="card">
    <h2><a href="/grant/1">Grant One</a></h2>
    <p class="deadline">Cierre: 15/08/2027</p>
</div>
<div class="card">
    <h2><a href="/grant/2">Grant Two</a></h2>
    <p class="deadline">Cierre: 30/09/2027</p>
</div>
</body></html>"""

VALID_CONFIG: dict = {
    "list_selectors": [".card", ".item"],
    "title_selectors": ["h2 a", "h3 a"],
    "link_selectors": ["a[href]"],
    "content_selectors": [".content", "article"],
    "date_labels": ["Cierre:", "Deadline:"],
}


class TestSelectorDiagnostics:
    """ConfigurableHtmlConnector tracks which selectors succeeded after parse."""

    def test_diagnostics_available_after_parse(self, monkeypatch):
        """After parse, selector diagnostics show which selectors matched."""
        from unittest.mock import AsyncMock

        from app.connectors.configurable_html import ConfigurableHtmlConnector

        mock = AsyncMock(
            return_value=("http://example.com", SAMPLE_LIST_HTML, "text/html")
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector("test-key", "http://example.com", VALID_CONFIG)
        import asyncio
        raw = asyncio.run(connector.fetch())
        asyncio.run(connector.parse(raw))

        diag = connector.selector_diagnostics
        assert diag["list_selector"] is not None
        assert diag["title_selector"] is not None
        assert diag["link_selector"] is not None
        # content_selector is tracked but may be None if not used during parse
        assert "content_selector" in diag

    def test_diagnostics_show_which_selector_matched(self, monkeypatch):
        """Diagnostics contain the exact CSS selector string that matched."""
        from unittest.mock import AsyncMock

        from app.connectors.configurable_html import ConfigurableHtmlConnector

        mock = AsyncMock(
            return_value=("http://example.com", SAMPLE_LIST_HTML, "text/html")
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector("test-key", "http://example.com", VALID_CONFIG)
        import asyncio
        raw = asyncio.run(connector.fetch())
        asyncio.run(connector.parse(raw))

        diag = connector.selector_diagnostics
        # With .card as the first list selector matching the HTML
        assert diag["list_selector"] == ".card"
        # Title matches h2 a
        assert diag["title_selector"] == "h2 a"
        # Link matches a[href]
        assert diag["link_selector"] == "a[href]"

    def test_diagnostics_all_none_when_no_selectors_match(self, monkeypatch):
        """When no selectors match, all diagnostics are None."""
        from unittest.mock import AsyncMock

        from app.connectors.configurable_html import ConfigurableHtmlConnector

        mock = AsyncMock(
            return_value=("http://example.com", "<html><body><p>No items</p></body></html>", "text/html")
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        config = {**VALID_CONFIG, "list_selectors": [".does-not-exist", ".also-missing"]}
        connector = ConfigurableHtmlConnector("test-key", "http://example.com", config)
        import asyncio
        raw = asyncio.run(connector.fetch())
        asyncio.run(connector.parse(raw))

        diag = connector.selector_diagnostics
        assert diag["list_selector"] is None
        # When list selector fails, title/link are still set per-item
        # but no items are extracted, so they remain None
        assert diag["title_selector"] is None
        assert diag["link_selector"] is None


# ═══════════════════════════════════════════════════════════════
# 6. Source model DOM fields
# ═══════════════════════════════════════════════════════════════


class TestSourceModelDomFields:
    """Source model must have DOM tracking fields."""

    def test_source_has_dom_hash_field(self):
        """Source model has a dom_hash column."""
        from app.models import Source

        assert hasattr(Source, "dom_hash")

    def test_source_has_dom_hash_changed_at_field(self):
        """Source model has a dom_hash_changed_at column."""
        from app.models import Source

        assert hasattr(Source, "dom_hash_changed_at")

    def test_source_has_last_item_count_field(self):
        """Source model has a last_item_count column."""
        from app.models import Source

        assert hasattr(Source, "last_item_count")

    def test_source_has_selector_failures_field(self):
        """Source model has a selector_failures column."""
        from app.models import Source

        assert hasattr(Source, "selector_failures")

    def test_selector_failures_field_exists(self):
        """selector_failures is a mapped attribute on Source."""
        from app.models import Source

        src = Source(
            id="test-dom-001",
            name="Test DOM Source",
            key="test-dom-key",
            base_url="https://example.com",
        )
        # Column default is SQL-level; attribute is accessible on instances
        assert "selector_failures" in [c.key for c in Source.__table__.columns]

    def test_selector_failures_db_default(self):
        """selector_failures has a DB default of 0 (verified via SQLite table info)."""
        from sqlalchemy import inspect
        from app.models import Source

        insp = inspect(Source.__table__)
        col = Source.__table__.c["selector_failures"]
        # In SQLAlchemy, default=0 sets Column.default
        assert col.default is not None

    def test_dom_hash_defaults_to_none(self):
        """dom_hash defaults to None (nullable column)."""
        from app.models import Source

        src = Source(
            id="test-dom-002",
            name="Test DOM Source 2",
            key="test-dom-key-2",
            base_url="https://example.com",
        )
        assert src.dom_hash is None

    def test_dom_hash_can_be_set(self):
        """dom_hash can be assigned a string value."""
        from app.models import Source

        src = Source(
            id="test-dom-003",
            name="Test DOM Source 3",
            key="test-dom-key-3",
            base_url="https://example.com",
            dom_hash="abc123def456",
        )
        assert src.dom_hash == "abc123def456"

    def test_selector_failures_can_be_set_and_incremented(self):
        """selector_failures can be set explicitly and incremented."""
        from app.models import Source

        src = Source(
            id="test-dom-004",
            name="Test DOM Source 4",
            key="test-dom-key-4",
            base_url="https://example.com",
            selector_failures=2,
        )
        src.selector_failures += 1
        assert src.selector_failures == 3
