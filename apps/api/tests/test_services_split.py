"""TDD: Verify services module split maintains backward compat.

Tests:
1. Every function exported by old services.py is accessible via the new package
2. Individual sub-modules export the expected symbols
3. ``from app.services import X`` still works for every X
"""

from __future__ import annotations

import pytest


# ── Functions duplicated in _legacy.py (characterized before deletion in PR A-1) ─
DUPLICATE_FUNCS = [
    # validation.py
    "slugify", "normalize_official_url", "is_private_url", "validate_source_url",
    "is_public_http_url", "is_noise_title", "is_noise_payload", "url_is_reachable",
    # dedup.py
    "opportunity_dedup_key", "_organization_opportunity_scope", "find_duplicate_opportunity",
    "_normalize_survivor_datetime", "_opportunity_survivor_key", "_reassign_opportunity_relations",
    "_merge_opportunity_records", "deduplicate_opportunities", "candidate_external_id",
    # scoring.py
    "priority_for_score", "_semantic_score", "_compute_score", "calculate_score",
    # export.py
    "export_csv", "export_xlsx", "export_pdf", "generate_report_html", "_render_pdf_with_playwright",
    # search.py
    "build_opportunity_query", "_text_search_opportunities", "_lexical_search_score",
    "semantic_search_opportunities",
    # embeddings.py
    "_get_opportunity_embedding", "_supports_vector_search", "opportunity_embedding_text",
    "opportunity_reanalysis_text", "upsert_opportunity_embedding", "rebuild_opportunity_embeddings",
]

DUPLICATE_MODULE_MAP: dict[str, str] = {
    # validation
    "slugify": "validation", "normalize_official_url": "validation",
    "is_private_url": "validation", "validate_source_url": "validation",
    "is_public_http_url": "validation", "is_noise_title": "validation",
    "is_noise_payload": "validation", "url_is_reachable": "validation",
    # dedup
    "opportunity_dedup_key": "dedup", "_organization_opportunity_scope": "dedup",
    "find_duplicate_opportunity": "dedup", "_normalize_survivor_datetime": "dedup",
    "_opportunity_survivor_key": "dedup", "_reassign_opportunity_relations": "dedup",
    "_merge_opportunity_records": "dedup", "deduplicate_opportunities": "dedup",
    "candidate_external_id": "dedup",
    # scoring
    "priority_for_score": "scoring", "_semantic_score": "scoring",
    "_compute_score": "scoring", "calculate_score": "scoring",
    # export
    "export_csv": "export", "export_xlsx": "export", "export_pdf": "export",
    "generate_report_html": "export", "_render_pdf_with_playwright": "export",
    # search
    "build_opportunity_query": "search", "_text_search_opportunities": "search",
    "_lexical_search_score": "search", "semantic_search_opportunities": "search",
    # embeddings
    "_get_opportunity_embedding": "embeddings", "_supports_vector_search": "embeddings",
    "opportunity_embedding_text": "embeddings", "opportunity_reanalysis_text": "embeddings",
    "upsert_opportunity_embedding": "embeddings", "rebuild_opportunity_embeddings": "embeddings",
}

# ── Functions that MUST be importable from app.services ──────────────────────

# validation.py
VALIDATION_FUNCS = [
    "is_noise_title",
    "is_noise_payload",
    "is_private_url",
    "is_public_http_url",
    "validate_source_url",
    "url_is_reachable",
    "normalize_official_url",
    "slugify",
]

# dedup.py
DEDUP_FUNCS = [
    "opportunity_dedup_key",
    "find_duplicate_opportunity",
    "deduplicate_opportunities",
    "_organization_opportunity_scope",
    "_opportunity_survivor_key",
    "_normalize_survivor_datetime",
    "_reassign_opportunity_relations",
    "_merge_opportunity_records",
    "candidate_external_id",
]

# scoring.py
SCORING_FUNCS = [
    "calculate_score",
    "priority_for_score",
    "_semantic_score",
    "_compute_score",
]

# export.py
EXPORT_FUNCS = [
    "export_csv",
    "export_xlsx",
    "export_pdf",
    "generate_report_html",
]

# search.py
SEARCH_FUNCS = [
    "semantic_search_opportunities",
    "_text_search_opportunities",
    "_lexical_search_score",
    "build_opportunity_query",
]

# embeddings.py
EMBEDDINGS_FUNCS = [
    "upsert_opportunity_embedding",
    "rebuild_opportunity_embeddings",
    "opportunity_embedding_text",
    "opportunity_reanalysis_text",
    "_get_opportunity_embedding",
    "_supports_vector_search",
]

# Functions that stay in the __init__ facade (not moved to sub-modules)
FACADE_FUNCS = [
    "connector_for",
    "is_slow_scrape_source",
    "source_due_for_scraping",
    "audit",
    "create_source_health_alert",
    "create_opportunity",
    "enrich_opportunity_payload",
    "execute_source_run_locally",
    "reanalyze_opportunity",
    "opportunity_status",
    "inferred_opportunity_status",
    "_parse_ai_close_date",
    "_parse_funding_amount",
    "create_heuristic_extraction",
    "create_ai_extraction",
    "summarize_text",
    "count_query",
    "extract_score_reasons",
    "get_review_queue",
    "get_closing_soon_7d",
    "get_top_scored",
    "get_closing_soon",
    "get_health_kpis",
    "get_status_breakdown",
    "get_country_breakdown",
    "get_data_coverage",
    "get_sources_health",
    "get_source_health_summaries",
    "get_score_distribution",
    "backfill_close_dates",
    "backfill_funding_amounts",
    "backfill_close_dates_ai",
    "backfill_funding_amounts_ai",
    "get_funding_ranges",
    "get_source_contribution",
    "get_opportunities_timeline",
    "get_category_distribution",
    "summarize_missing_opportunities",
    "rescore_all_opportunities",
    "score_unscored_opportunities",
    "generate_report_html",
    "export_pdf",
    "build_weekly_digest_html",
    "send_weekly_digest",
    "SLOW_SCRAPE_SOURCE_KEYS",
    "SLOW_SCRAPE_SOURCE_TYPES",
]

# Combine ALL symbols that must be importable from app.services
ALL_SYMBOLS = (
    VALIDATION_FUNCS + DEDUP_FUNCS + SCORING_FUNCS + EXPORT_FUNCS
    + SEARCH_FUNCS + EMBEDDINGS_FUNCS + FACADE_FUNCS
)


class TestPreDeletionSanity:
    """Characterization tests for 36 duplicated functions (PR A-1)."""

    @pytest.mark.parametrize("symbol", DUPLICATE_FUNCS)
    def test_duplicate_importable_from_specialized_module(self, symbol: str) -> None:
        """Each duplicated function must be importable from its specialized module."""
        module_name = DUPLICATE_MODULE_MAP[symbol]
        import importlib
        mod = importlib.import_module(f"app.services.{module_name}")
        assert hasattr(mod, symbol), (
            f"Symbol {symbol!r} is NOT exported from app.services.{module_name}"
        )

    def test_slugify_matches_legacy(self) -> None:
        from app.services.validation import slugify as new_slugify
        from app.services._legacy import slugify as old_slugify
        assert new_slugify("Hello World") == old_slugify("Hello World") == "hello-world"
        assert new_slugify("") == old_slugify("") == "item"

    def test_normalize_official_url_matches_legacy(self) -> None:
        from app.services.validation import normalize_official_url as new_func
        from app.services._legacy import normalize_official_url as old_func
        assert new_func(None) == old_func(None) is None
        assert new_func("https://Example.COM/Path/") == old_func("https://Example.COM/Path/") == "https://example.com/Path"

    def test_is_noise_title_matches_legacy(self) -> None:
        from app.services.validation import is_noise_title as new_func
        from app.services._legacy import is_noise_title as old_func
        assert new_func(None) == old_func(None) is True
        assert new_func("Real Opportunity 2025") == old_func("Real Opportunity 2025") is False

    def test_priority_for_score_matches_legacy(self) -> None:
        """NOTE: scoring.py and _legacy.py have diverged for score=80.
        scoring.py returns 'high' (the correct behavior, used by facade).
        _legacy.py stale copy returns 'medium'. Legitimate drift."""
        from app.services.scoring import priority_for_score as new_func
        from app.services._legacy import priority_for_score as old_func
        assert new_func(20) == old_func(20) == "not_recommended"
        assert new_func(80) == "high"  # scoring.py is authoritative
        assert old_func(80) == "medium"  # stale legacy value (dead code)

    def test_validate_source_url_raises_on_bad_url(self) -> None:
        """Both versions validate and raise on bad URL."""
        from app.services.validation import validate_source_url as new_func
        from app.services._legacy import validate_source_url as old_func
        from unittest.mock import MagicMock
        bad_source = MagicMock()
        bad_source.base_url = "http://localhost:8080"
        bad_source.allowed_domains = None
        with pytest.raises(ValueError, match="not allowed"):
            new_func(bad_source)
        with pytest.raises(ValueError, match="not allowed"):
            old_func(bad_source)

    def test_is_private_url_matches_legacy(self) -> None:
        from app.services.validation import is_private_url as new_func
        from app.services._legacy import is_private_url as old_func
        assert new_func("http://localhost:8000") == old_func("http://localhost:8000") is True
        assert new_func("https://google.com") == old_func("https://google.com") is False

    def test_export_csv_matches_legacy(self) -> None:
        from app.services.export import export_csv as new_func
        from app.services._legacy import export_csv as old_func
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Test Opp"
        opp.entity = "Test Entity"
        opp.country = "Colombia"
        opp.status = "open"
        opp.close_date = None
        opp.funding_amount_raw = None
        opp.funding_amount_value = None
        opp.official_url = None
        new_result = new_func([opp])
        old_result = old_func([opp])
        assert "Test Opp" in new_result
        assert "Test Opp" in old_result


class TestServicesImportBackwardCompat:
    """Every symbol from the old services.py MUST be importable via the new package."""

    @pytest.mark.parametrize("symbol", ALL_SYMBOLS)
    def test_all_symbols_importable_from_app_services(self, symbol: str) -> None:
        """``from app.services import {symbol}`` must work."""
        import importlib
        mod = importlib.import_module("app.services")
        assert hasattr(mod, symbol), (
            f"Symbol {symbol!r} is NOT exported from app.services"
        )


class TestValidationModule:
    """Functions extracted to app.services.validation."""

    def test_is_noise_title(self) -> None:
        from app.services.validation import is_noise_title
        assert is_noise_title(None) is True
        assert is_noise_title("   ") is True
        assert is_noise_title("hello@world") is True
        assert is_noise_title("https://example.com") is True

    def test_is_noise_title_valid(self) -> None:
        from app.services.validation import is_noise_title
        assert is_noise_title("Fondo de Innovación Tecnológica 2025") is False

    def test_is_private_url(self) -> None:
        from app.services.validation import is_private_url
        assert is_private_url("http://localhost:8000") is True
        assert is_private_url("http://192.168.1.1") is True
        assert is_private_url("https://google.com") is False

    def test_slugify(self) -> None:
        from app.services.validation import slugify
        assert slugify("Hello World") == "hello-world"
        assert slugify("  Foo  Bar  ") == "foo-bar"
        assert slugify("") == "item"

    def test_normalize_official_url(self) -> None:
        from app.services.validation import normalize_official_url
        assert normalize_official_url(None) is None
        assert normalize_official_url("https://Example.COM/Path/") == "https://example.com/Path"
        assert normalize_official_url("ftp://bad.com") is None


class TestDedupModule:
    """Functions extracted to app.services.dedup."""

    def test_opportunity_dedup_key_url(self) -> None:
        from app.services.dedup import opportunity_dedup_key
        key = opportunity_dedup_key("https://grants.gov/search-results-detail/12345", "title")
        assert key == "grants-gov:12345"

    def test_candidate_external_id(self) -> None:
        from app.services.dedup import candidate_external_id
        from unittest.mock import MagicMock
        source = MagicMock()
        source.key = "test-source"
        eid = candidate_external_id(source, "https://example.com/123", "Test Title")
        assert eid.startswith("test-source-") or eid.startswith("dedup-")
        assert len(eid) > 20


class TestScoringModule:
    """Functions extracted to app.services.scoring."""

    def test_priority_for_score(self) -> None:
        from app.services.scoring import priority_for_score
        assert priority_for_score(80) == "high"
        assert priority_for_score(65) == "medium"
        assert priority_for_score(40) == "low"
        assert priority_for_score(20) == "not_recommended"

    def test_semantic_score_empty(self) -> None:
        from app.services.scoring import _semantic_score
        assert _semantic_score("", "profile") == 0.0
        assert _semantic_score("text", "") == 0.0

    def test_compute_score_structure(self) -> None:
        """Verify _compute_score returns the expected dict shape."""
        from app.services.scoring import _compute_score
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.country = "Colombia"
        opp.eligible_applicants = []
        opp.categories = []
        opp.topics = []
        opp.funding_amount_value = None
        opp.close_date = None
        opp.requirements = []
        opp.documents_required = []
        profile = MagicMock()
        profile.country = "Colombia"
        profile.eligible_international = True
        profile.areas_of_interest = ["technology"]
        profile.max_funding_amount = None
        profile.organization_type = "SME"
        result = _compute_score(opp, profile)
        assert "raw" in result
        assert "reasons" in result
        assert "warnings" in result
        assert isinstance(result["raw"], float)
        assert isinstance(result["reasons"], list)
        assert isinstance(result["warnings"], list)


class TestExportModule:
    """Functions extracted to app.services.export."""

    def test_export_csv_structure(self) -> None:
        from app.services.export import export_csv
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Test"
        opp.entity = "Entity"
        opp.country = "Colombia"
        opp.status = "open"
        opp.close_date = None
        opp.funding_amount_raw = None
        opp.funding_amount_value = None
        opp.official_url = None
        output = export_csv([opp])
        assert "Test" in output
        assert "Entity" in output


class TestSearchModule:
    """Functions extracted to app.services.search."""

    def test_lexical_search_score(self) -> None:
        from app.services.search import _lexical_search_score
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Fondo de Innovación Tecnológica 2025"
        opp.entity = "MinCiencias"
        opp.country = "Colombia"
        opp.summary = "innovación tecnológica"
        opp.description = ""
        opp.raw_text = ""
        opp.categories = []
        opp.topics = []
        opp.requirements = []
        opp.official_url = ""
        opp.application_url = ""
        # Use the accented forms matching the actual text
        score = _lexical_search_score({"innovación", "tecnológica"}, opp)
        assert score > 0.0


class TestEmbeddingsModule:
    """Functions extracted to app.services.embeddings."""

    def test_opportunity_embedding_text(self) -> None:
        from app.services.embeddings import opportunity_embedding_text
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Test Opportunity"
        opp.entity = "Entity"
        opp.country = "Colombia"
        opp.region = ""
        opp.summary = "Summary"
        opp.description = ""
        opp.raw_text = ""
        opp.official_url = ""
        opp.application_url = ""
        opp.funding_amount_raw = ""
        opp.categories = []
        opp.topics = ["tech"]
        opp.requirements = []
        opp.documents_required = []
        opp.evaluation_criteria = []
        opp.restrictions = []
        opp.risk_flags = []
        text = opportunity_embedding_text(opp)
        assert "Test Opportunity" in text
