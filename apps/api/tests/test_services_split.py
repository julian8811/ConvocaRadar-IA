"""TDD: Verify services module split maintains backward compat.

Tests:
1. Every function exported by old services.py is accessible via the new package
2. Individual sub-modules export the expected symbols
3. ``from app.services import X`` still works for every X
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


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

# analytics.py
ANALYTICS_FUNCS = [
    "_backfill_close_date_text",
    "_opportunity_combined_text",
    "backfill_close_dates",
    "backfill_close_dates_ai",
    "backfill_funding_amounts",
    "backfill_funding_amounts_ai",
    "get_category_distribution",
    "get_funding_ranges",
    "get_opportunities_timeline",
    "get_score_distribution",
    "get_source_contribution",
]

# genai.py
GENAI_FUNCS = [
    "build_weekly_digest_html",
    "rescore_all_opportunities",
    "score_unscored_opportunities",
    "send_weekly_digest",
    "summarize_missing_opportunities",
]

# connectors.py
CONNECTORS_FUNCS = [
    "connector_for",
    "is_slow_scrape_source",
    "source_due_for_scraping",
    "execute_source_run_locally",
    "_scrape_source_candidates",
    "_scrape_source_candidates_with_timeout",
    "SLOW_SCRAPE_SOURCE_KEYS",
    "SLOW_SCRAPE_SOURCE_TYPES",
]

# opportunity.py
OPPORTUNITY_FUNCS = [
    "_combined_text",
    "_parse_ai_close_date",
    "_parse_funding_amount",
    "create_opportunity",
    "enrich_opportunity_payload",
    "inferred_opportunity_status",
    "opportunity_status",
    "reanalyze_opportunity",
    "create_ai_extraction",
    "create_heuristic_extraction",
    "summarize_text",
    "count_query",
]

# Functions that stay in the __init__ facade (not moved to sub-modules)
FACADE_FUNCS = [
    "audit",
    "create_source_health_alert",
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
]

# Combine ALL symbols that must be importable from app.services
ALL_SYMBOLS = (
    VALIDATION_FUNCS + DEDUP_FUNCS + SCORING_FUNCS + EXPORT_FUNCS
    + SEARCH_FUNCS + EMBEDDINGS_FUNCS + ANALYTICS_FUNCS + GENAI_FUNCS
    + CONNECTORS_FUNCS + OPPORTUNITY_FUNCS
    + FACADE_FUNCS
)





class TestDashboardTriageModule:
    """Characterization for 5 triage functions extracted to dashboard.py (PR B-1a).
    
    NOTE: These reference app.services.dashboard which does NOT exist yet.
    They fail until dashboard.py is created (GREEN step).
    """

    def test_extract_score_reasons_pure(self) -> None:
        """extract_score_reasons is a pure function — characterize known inputs."""
        from app.services.dashboard import extract_score_reasons

        assert extract_score_reasons(None) == []
        assert extract_score_reasons([]) == []
        assert extract_score_reasons(["a", "b"]) == ["a", "b"]
        assert extract_score_reasons('["a", "b"]') == ["a", "b"]
        assert extract_score_reasons("a, b") == ["a", "b"]
        assert extract_score_reasons(42) == []
        assert extract_score_reasons("") == []

    def test__triage_days_to_close_none(self) -> None:
        """_triage_days_to_close returns None when close_date is None."""
        from app.services.dashboard import _triage_days_to_close
        assert _triage_days_to_close(None) is None

    def test_get_review_queue_signature(self) -> None:
        """get_review_queue is callable with typical args."""
        from app.services.dashboard import get_review_queue
        from inspect import signature
        sig = signature(get_review_queue)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_closing_soon_7d_signature(self) -> None:
        """get_closing_soon_7d is callable with typical args."""
        from app.services.dashboard import get_closing_soon_7d
        from inspect import signature
        sig = signature(get_closing_soon_7d)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test__STATUS_LABELS_content(self) -> None:
        """_STATUS_LABELS is a dict with expected keys and Spanish labels."""
        from app.services.dashboard import _STATUS_LABELS
        assert isinstance(_STATUS_LABELS, dict)
        assert _STATUS_LABELS["open"] == "Abiertas"
        assert _STATUS_LABELS["closing_soon"] == "Cierran pronto"
        assert _STATUS_LABELS["closed"] == "Cerradas"
        assert _STATUS_LABELS["unknown"] == "Sin fecha"

    def test_dashboard_facade_re_exports(self) -> None:
        """The facade re-exports triage symbols from app.services."""
        from app.services import (
            extract_score_reasons,
            _triage_days_to_close,
            get_review_queue,
            get_closing_soon_7d,
            _STATUS_LABELS,
        )
        assert callable(extract_score_reasons)
        assert callable(_triage_days_to_close)
        assert callable(get_review_queue)
        assert callable(get_closing_soon_7d)
        assert isinstance(_STATUS_LABELS, dict)


class TestDashboardPipelineModule:
    """Characterization for 3 pipeline functions (PR B-1b).

    These reference app.services.dashboard functions that are NOT yet
    defined — they fail until the GREEN step adds them.
    """

    def test__pipeline_days_to_close_none(self) -> None:
        """_pipeline_days_to_close returns None when close_date is None."""
        from app.services.dashboard import _pipeline_days_to_close
        assert _pipeline_days_to_close(None) is None

    def test__pipeline_days_to_close_clamps_negative(self) -> None:
        """_pipeline_days_to_close clamps negative to 0."""
        from datetime import timedelta
        from app.services.dashboard import _pipeline_days_to_close
        # Must use naive UTC to match the function's internal behavior
        yesterday = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        assert _pipeline_days_to_close(yesterday) == 0

    def test_get_top_scored_signature(self) -> None:
        """get_top_scored is callable with typical args."""
        from app.services.dashboard import get_top_scored
        from inspect import signature
        sig = signature(get_top_scored)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_closing_soon_signature(self) -> None:
        """get_closing_soon is callable with typical args."""
        from app.services.dashboard import get_closing_soon
        from inspect import signature
        sig = signature(get_closing_soon)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters
        assert "days_window" in sig.parameters


class TestDashboardHealthModule:
    """Characterization for 6 health functions (PR B-1c).

    These reference app.services.dashboard functions that are NOT yet
    defined — they fail until the GREEN step adds them.
    """

    def test_get_health_kpis_signature(self) -> None:
        """get_health_kpis is callable with typical args."""
        from app.services.dashboard import get_health_kpis
        from inspect import signature
        sig = signature(get_health_kpis)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_status_breakdown_signature(self) -> None:
        """get_status_breakdown is callable with typical args."""
        from app.services.dashboard import get_status_breakdown
        from inspect import signature
        sig = signature(get_status_breakdown)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_country_breakdown_signature(self) -> None:
        """get_country_breakdown is callable with typical args."""
        from app.services.dashboard import get_country_breakdown
        from inspect import signature
        sig = signature(get_country_breakdown)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_data_coverage_signature(self) -> None:
        """get_data_coverage is callable with typical args."""
        from app.services.dashboard import get_data_coverage
        from inspect import signature
        sig = signature(get_data_coverage)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_sources_health_signature(self) -> None:
        """get_sources_health is callable with typical args."""
        from app.services.dashboard import get_sources_health
        from inspect import signature
        sig = signature(get_sources_health)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_source_health_summaries_signature(self) -> None:
        """get_source_health_summaries is callable with typical args."""
        from app.services.dashboard import get_source_health_summaries
        from inspect import signature
        sig = signature(get_source_health_summaries)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters


class TestAnalyticsModule:
    """Characterization for 11 analytics functions to be extracted to analytics.py (PR B-2).

    These reference app.services.analytics which does NOT exist yet.
    They fail until analytics.py is created (GREEN step).
    """

    def test_get_score_distribution_signature(self) -> None:
        """get_score_distribution is callable with db + organization_id."""
        from app.services.analytics import get_score_distribution
        from inspect import signature
        sig = signature(get_score_distribution)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test__backfill_close_date_text_pure(self) -> None:
        """_backfill_close_date_text is a pure function."""
        from app.services.analytics import _backfill_close_date_text
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Test Grant"
        opp.summary = "Summary text"
        opp.description = "Description text"
        opp.raw_text = "Raw text"
        result = _backfill_close_date_text(opp)
        assert "Test Grant" in result
        assert "Summary text" in result
        assert "Description text" in result
        assert "Raw text" in result

    def test__backfill_close_date_text_skips_none_parts(self) -> None:
        """_backfill_close_date_text skips None parts."""
        from app.services.analytics import _backfill_close_date_text
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Title only"
        opp.summary = None
        opp.description = None
        opp.raw_text = None
        result = _backfill_close_date_text(opp)
        assert result == "Title only"

    def test_backfill_close_dates_signature(self) -> None:
        """backfill_close_dates is callable with typical args."""
        from app.services.analytics import backfill_close_dates
        from inspect import signature
        sig = signature(backfill_close_dates)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_backfill_funding_amounts_signature(self) -> None:
        """backfill_funding_amounts is callable with typical args."""
        from app.services.analytics import backfill_funding_amounts
        from inspect import signature
        sig = signature(backfill_funding_amounts)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test__opportunity_combined_text_pure(self) -> None:
        """_opportunity_combined_text joins all text fields."""
        from app.services.analytics import _opportunity_combined_text
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Title"
        opp.summary = "Summary"
        opp.description = "Description"
        opp.raw_text = "Raw"
        result = _opportunity_combined_text(opp)
        assert result == "Title Summary Description Raw"

    def test__opportunity_combined_text_skips_none(self) -> None:
        """_opportunity_combined_text skips None parts."""
        from app.services.analytics import _opportunity_combined_text
        from unittest.mock import MagicMock
        opp = MagicMock()
        opp.title = "Title"
        opp.summary = None
        opp.description = None
        opp.raw_text = None
        result = _opportunity_combined_text(opp)
        assert result == "Title"

    def test_backfill_close_dates_ai_signature(self) -> None:
        """backfill_close_dates_ai is an async callable."""
        from app.services.analytics import backfill_close_dates_ai
        from inspect import signature, Parameter
        sig = signature(backfill_close_dates_ai)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_backfill_funding_amounts_ai_signature(self) -> None:
        """backfill_funding_amounts_ai is an async callable."""
        from app.services.analytics import backfill_funding_amounts_ai
        from inspect import signature
        sig = signature(backfill_funding_amounts_ai)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_funding_ranges_signature(self) -> None:
        """get_funding_ranges is callable with db + organization_id."""
        from app.services.analytics import get_funding_ranges
        from inspect import signature
        sig = signature(get_funding_ranges)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_source_contribution_signature(self) -> None:
        """get_source_contribution is callable with db + organization_id."""
        from app.services.analytics import get_source_contribution
        from inspect import signature
        sig = signature(get_source_contribution)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_opportunities_timeline_signature(self) -> None:
        """get_opportunities_timeline is callable with db + organization_id."""
        from app.services.analytics import get_opportunities_timeline
        from inspect import signature
        sig = signature(get_opportunities_timeline)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_get_category_distribution_signature(self) -> None:
        """get_category_distribution is callable with db + organization_id."""
        from app.services.analytics import get_category_distribution
        from inspect import signature
        sig = signature(get_category_distribution)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters


class TestGenaiModule:
    """Characterization for 5 genai/digest functions to be extracted to genai.py (PR B-3).

    These reference app.services.genai which does NOT exist yet.
    They fail until genai.py is created (GREEN step).
    """

    def test_summarize_missing_opportunities_signature(self) -> None:
        """summarize_missing_opportunities is callable with db + organization_id."""
        from app.services.genai import summarize_missing_opportunities
        from inspect import signature
        sig = signature(summarize_missing_opportunities)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_rescore_all_opportunities_signature(self) -> None:
        """rescore_all_opportunities is callable with db + organization_id."""
        from app.services.genai import rescore_all_opportunities
        from inspect import signature
        sig = signature(rescore_all_opportunities)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_score_unscored_opportunities_signature(self) -> None:
        """score_unscored_opportunities is callable with db + organization_id."""
        from app.services.genai import score_unscored_opportunities
        from inspect import signature
        sig = signature(score_unscored_opportunities)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters

    def test_build_weekly_digest_html_pure(self) -> None:
        """build_weekly_digest_html is callable with kwargs."""
        from app.services.genai import build_weekly_digest_html
        from inspect import signature
        sig = signature(build_weekly_digest_html)
        assert "organization" in sig.parameters
        assert "opportunities" in sig.parameters

    def test_build_weekly_digest_html_structure(self) -> None:
        """build_weekly_digest_html produces expected HTML structure."""
        from app.services.genai import build_weekly_digest_html
        from unittest.mock import MagicMock
        org = MagicMock()
        org.name = "Test Org"
        opp = MagicMock()
        opp.title = "Test Grant"
        opp.entity = "MinCiencia"
        opp.country = "Colombia"
        opp.summary = "A research opportunity"
        opp.description = None
        opp.official_url = "https://example.com/grant"
        opp.application_url = None
        html = build_weekly_digest_html(organization=org, opportunities=[opp])
        assert "<html>" in html
        assert "Test Grant" in html
        assert "Test Org" in html
        assert "Resumen semanal" in html

    def test_send_weekly_digest_signature(self) -> None:
        """send_weekly_digest is callable with db + organization_id."""
        from app.services.genai import send_weekly_digest
        from inspect import signature
        sig = signature(send_weekly_digest)
        assert "db" in sig.parameters
        assert "organization_id" in sig.parameters


class TestConnectorsModule:
    """Characterization for 8 connectors/scraping functions (to be extracted to connectors.py, PR C-1).

    These reference app.services.connectors which does NOT exist yet.
    They fail until connectors.py is created (GREEN step).
    """

    def test_connector_for_signature(self) -> None:
        """connector_for is callable with source_key."""
        from app.services.connectors import connector_for
        from inspect import signature
        sig = signature(connector_for)
        assert "source_key" in sig.parameters

    def test_is_slow_scrape_source_matches_key(self) -> None:
        """is_slow_scrape_source returns True for known slow keys."""
        from app.services.connectors import is_slow_scrape_source, SLOW_SCRAPE_SOURCE_KEYS
        from unittest.mock import MagicMock
        source = MagicMock()
        source.key = next(iter(SLOW_SCRAPE_SOURCE_KEYS))
        source.source_type = "rss"
        assert is_slow_scrape_source(source) is True

    def test_is_slow_scrape_source_not_slow(self) -> None:
        """is_slow_scrape_source returns False for normal keys."""
        from app.services.connectors import is_slow_scrape_source
        from unittest.mock import MagicMock
        source = MagicMock()
        source.key = "fast-source"
        source.source_type = "rss"
        assert is_slow_scrape_source(source) is False

    def test_source_due_for_scraping_no_last_run(self) -> None:
        """source_due_for_scraping returns True when never run."""
        from app.services.connectors import source_due_for_scraping
        from unittest.mock import MagicMock
        source = MagicMock()
        source.last_run_at = None
        source.scraping_frequency = "daily"
        assert source_due_for_scraping(source) is True

    def test_source_due_for_scraping_hourly(self) -> None:
        """source_due_for_scraping returns True for hourly frequency."""
        from app.services.connectors import source_due_for_scraping
        from unittest.mock import MagicMock
        source = MagicMock()
        source.scraping_frequency = "hourly"
        source.last_run_at = None
        assert source_due_for_scraping(source) is True

    def test_SLOW_SCRAPE_SOURCE_KEYS_content(self) -> None:
        """SLOW_SCRAPE_SOURCE_KEYS is a frozenset with expected entries."""
        from app.services.connectors import SLOW_SCRAPE_SOURCE_KEYS
        assert isinstance(SLOW_SCRAPE_SOURCE_KEYS, frozenset)
        assert "innovamos-global-innovation-fund" in SLOW_SCRAPE_SOURCE_KEYS
        assert "apc-colombia" in SLOW_SCRAPE_SOURCE_KEYS

    def test_SLOW_SCRAPE_SOURCE_TYPES_content(self) -> None:
        """SLOW_SCRAPE_SOURCE_TYPES is a frozenset with 'hybrid'."""
        from app.services.connectors import SLOW_SCRAPE_SOURCE_TYPES
        assert isinstance(SLOW_SCRAPE_SOURCE_TYPES, frozenset)
        assert "hybrid" in SLOW_SCRAPE_SOURCE_TYPES

    def test_execute_source_run_locally_signature(self) -> None:
        """execute_source_run_locally is callable with db + source."""
        from app.services.connectors import execute_source_run_locally
        from inspect import signature
        sig = signature(execute_source_run_locally)
        assert "db" in sig.parameters
        assert "source" in sig.parameters

    def test__scrape_source_candidates_signature(self) -> None:
        """_scrape_source_candidates is async callable with source."""
        from app.services.connectors import _scrape_source_candidates
        from inspect import signature
        sig = signature(_scrape_source_candidates)
        assert "source" in sig.parameters

    def test__scrape_source_candidates_with_timeout_signature(self) -> None:
        """_scrape_source_candidates_with_timeout is async callable."""
        from app.services.connectors import _scrape_source_candidates_with_timeout
        from inspect import signature
        sig = signature(_scrape_source_candidates_with_timeout)
        assert "source" in sig.parameters


class TestOpportunityModule:
    """Characterization for 14 opportunity lifecycle functions (PR C-2a).

    These reference app.services.opportunity which does NOT exist yet.
    They fail until opportunity.py is created (GREEN step).
    """

    def test__parse_ai_close_date_none(self) -> None:
        """_parse_ai_close_date returns None for empty input."""
        from app.services.opportunity import _parse_ai_close_date
        assert _parse_ai_close_date(None) is None
        assert _parse_ai_close_date("") is None

    def test__parse_ai_close_date_iso(self) -> None:
        """_parse_ai_close_date parses ISO format."""
        from app.services.opportunity import _parse_ai_close_date
        from datetime import datetime
        result = _parse_ai_close_date("2025-12-31")
        assert result is not None
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31

    def test__parse_ai_close_date_datetime(self) -> None:
        """_parse_ai_close_date passes through datetime objects."""
        from app.services.opportunity import _parse_ai_close_date
        from datetime import datetime
        now = datetime.now()
        assert _parse_ai_close_date(now) is now

    def test__parse_funding_amount_none(self) -> None:
        """_parse_funding_amount returns (None, None) for empty input."""
        from app.services.opportunity import _parse_funding_amount
        assert _parse_funding_amount(None) == (None, None)
        assert _parse_funding_amount("") == (None, None)

    def test__parse_funding_amount_usd(self) -> None:
        """_parse_funding_amount parses USD 500,000."""
        from app.services.opportunity import _parse_funding_amount
        val, cur = _parse_funding_amount("USD 500,000")
        assert val == 500000.0
        assert cur == "USD"

    def test__parse_funding_amount_eur_million(self) -> None:
        """_parse_funding_amount parses EUR 1.2 million."""
        from app.services.opportunity import _parse_funding_amount
        val, cur = _parse_funding_amount("EUR 1.2 million")
        assert val == 1200000.0
        assert cur == "EUR"

    def test__parse_funding_amount_cop(self) -> None:
        """_parse_funding_amount parses COP 5,000,000."""
        from app.services.opportunity import _parse_funding_amount
        val, cur = _parse_funding_amount("COP 5,000,000")
        assert val == 5000000.0
        assert cur == "COP"

    def test__parse_funding_amount_no_currency(self) -> None:
        """_parse_funding_amount returns (None,None) when no currency marker."""
        from app.services.opportunity import _parse_funding_amount
        assert _parse_funding_amount("500000") == (None, None)

    def test__combined_text_joins(self) -> None:
        """_combined_text joins all OpportunityCreate text fields."""
        from app.services.opportunity import _combined_text
        from unittest.mock import MagicMock
        data = MagicMock()
        data.title = "Title"
        data.summary = "Summary"
        data.description = "Description"
        data.raw_text = "Raw"
        result = _combined_text(data)
        assert result == "Title Summary Description Raw"

    def test__combined_text_skips_none(self) -> None:
        """_combined_text skips None/empty parts."""
        from app.services.opportunity import _combined_text
        from unittest.mock import MagicMock
        data = MagicMock()
        data.title = "Title"
        data.summary = None
        data.description = None
        data.raw_text = None
        result = _combined_text(data)
        assert result == "Title"

    def test_opportunity_status_unknown(self) -> None:
        """opportunity_status returns unknown when close_date is None."""
        from app.services.opportunity import opportunity_status
        assert opportunity_status(None) == "unknown"

    def test_inferred_opportunity_status_unknown_no_text(self) -> None:
        """inferred_opportunity_status returns unknown with no text hint."""
        from app.services.opportunity import inferred_opportunity_status
        assert inferred_opportunity_status(None) == "unknown"

    def test_inferred_opportunity_status_open_from_text(self) -> None:
        """inferred_opportunity_status returns open when text says 'open'."""
        from app.services.opportunity import inferred_opportunity_status
        assert inferred_opportunity_status(None, "This opportunity is open for") == "open"

    def test_create_heuristic_extraction_signature(self) -> None:
        """create_heuristic_extraction is callable with a text arg."""
        from app.services.opportunity import create_heuristic_extraction
        from inspect import signature
        sig = signature(create_heuristic_extraction)
        assert "text" in sig.parameters

    def test_create_ai_extraction_signature(self) -> None:
        """create_ai_extraction is an async callable."""
        from app.services.opportunity import create_ai_extraction
        from inspect import signature
        sig = signature(create_ai_extraction)
        assert "text" in sig.parameters

    def test_summarize_text_signature(self) -> None:
        """summarize_text is callable with a text arg."""
        from app.services.opportunity import summarize_text
        from inspect import signature
        sig = signature(summarize_text)
        assert "text" in sig.parameters

    def test_count_query_signature(self) -> None:
        """count_query is callable with db + stmt."""
        from app.services.opportunity import count_query
        from inspect import signature
        sig = signature(count_query)
        assert "db" in sig.parameters
        assert "stmt" in sig.parameters

    def test_enrich_opportunity_payload_signature(self) -> None:
        """enrich_opportunity_payload is async callable."""
        from app.services.opportunity import enrich_opportunity_payload
        from inspect import signature
        sig = signature(enrich_opportunity_payload)
        assert "data" in sig.parameters

    def test_reanalyze_opportunity_signature(self) -> None:
        """reanalyze_opportunity is async callable with db + opportunity."""
        from app.services.opportunity import reanalyze_opportunity
        from inspect import signature
        sig = signature(reanalyze_opportunity)
        assert "db" in sig.parameters
        assert "opportunity" in sig.parameters

    def test_create_opportunity_signature(self) -> None:
        """create_opportunity is async callable with db + data."""
        from app.services.opportunity import create_opportunity
        from inspect import signature
        sig = signature(create_opportunity)
        assert "db" in sig.parameters
        assert "data" in sig.parameters

    def test__update_opportunity_signature(self) -> None:
        """_update_opportunity is callable with opportunity + data + title."""
        from app.services.opportunity import _update_opportunity
        from inspect import signature
        sig = signature(_update_opportunity)
        assert "opportunity" in sig.parameters
        assert "data" in sig.parameters
        assert "normalized_title" in sig.parameters

    def test__update_and_score_signature(self) -> None:
        """_update_and_score is async callable with db + opportunity + data."""
        from app.services.opportunity import _update_and_score
        from inspect import signature
        sig = signature(_update_and_score)
        assert "db" in sig.parameters
        assert "opportunity" in sig.parameters
        assert "data" in sig.parameters


class TestAlertsModule:
    """Characterization for 3 audit/alert functions (PR C-2b).

    These reference app.services.alerts which does NOT exist yet.
    They fail until alerts.py is created (GREEN step).
    """

    def test_audit_signature(self) -> None:
        """audit is callable with db + action + resource_type + user."""
        from app.services.alerts import audit
        from inspect import signature
        sig = signature(audit)
        assert "db" in sig.parameters
        assert "action" in sig.parameters
        assert "resource_type" in sig.parameters
        assert "user" in sig.parameters

    def test__source_health_status_idle(self) -> None:
        """_source_health_status returns 'idle' for empty runs."""
        from app.services.alerts import _source_health_status
        assert _source_health_status([]) == "idle"

    def test__source_health_status_healthy(self) -> None:
        """_source_health_status returns 'healthy' when first run succeeded."""
        from app.services.alerts import _source_health_status
        from unittest.mock import MagicMock
        run = MagicMock()
        run.status = "completed"
        assert _source_health_status([run]) == "healthy"

    def test__source_health_status_failing_first_run(self) -> None:
        """_source_health_status returns 'failing' when first run failed."""
        from app.services.alerts import _source_health_status
        from unittest.mock import MagicMock
        run = MagicMock()
        run.status = "failed"
        assert _source_health_status([run]) == "failing"

    def test__source_health_status_failing_three_failures(self) -> None:
        """_source_health_status returns 'failing' with 3+ failures."""
        from app.services.alerts import _source_health_status
        from unittest.mock import MagicMock
        runs = [MagicMock(status="completed") for _ in range(2)]
        # Add 3 failed runs (after the initial successful ones)
        runs.insert(0, MagicMock(status="failed"))
        runs.insert(0, MagicMock(status="failed"))
        runs.insert(0, MagicMock(status="failed"))
        assert _source_health_status(runs) == "failing"

    def test__source_health_status_degraded(self) -> None:
        """_source_health_status returns 'degraded' with 1-2 non-first failures."""
        from app.services.alerts import _source_health_status
        from unittest.mock import MagicMock
        runs = [MagicMock(status="completed"), MagicMock(status="failed")]
        assert _source_health_status(runs) == "degraded"

    def test_create_source_health_alert_signature(self) -> None:
        """create_source_health_alert is callable with db + source + reason."""
        from app.services.alerts import create_source_health_alert
        from inspect import signature
        sig = signature(create_source_health_alert)
        assert "db" in sig.parameters
        assert "source" in sig.parameters
        assert "reason" in sig.parameters


class TestNoLegacyDuplicates:
    """PR A-1: Verify 36 duplicated functions are no longer defined in _legacy.py."""

    DELETED_SYMBOLS = [
        "slugify", "normalize_official_url", "is_private_url", "validate_source_url",
        "is_public_http_url", "is_noise_title", "is_noise_payload", "url_is_reachable",
        "opportunity_dedup_key", "_organization_opportunity_scope", "find_duplicate_opportunity",
        "_normalize_survivor_datetime", "_opportunity_survivor_key", "_reassign_opportunity_relations",
        "_merge_opportunity_records", "deduplicate_opportunities", "candidate_external_id",
        "priority_for_score", "_semantic_score", "_compute_score", "calculate_score",
        "export_csv", "export_xlsx", "export_pdf", "generate_report_html", "_render_pdf_with_playwright",
        "build_opportunity_query", "_text_search_opportunities", "_lexical_search_score",
        "semantic_search_opportunities",
        "_get_opportunity_embedding", "_supports_vector_search", "opportunity_embedding_text",
        "opportunity_reanalysis_text", "upsert_opportunity_embedding", "rebuild_opportunity_embeddings",
    ]

    @pytest.mark.parametrize("symbol", DELETED_SYMBOLS)
    def test_no_def_in_legacy_source(self, symbol: str) -> None:
        """Verify the function is no longer *defined* in the _legacy.py source."""
        import re
        with open("app/services/_legacy.py") as f:
            source = f.read()
        pattern = rf"^(?:async\s+)?def\s+{re.escape(symbol)}\s*\("
        assert not re.search(pattern, source, re.MULTILINE), (
            f"Function {symbol!r} is still *defined* in _legacy.py source"
        )

    def test_legacy_compiles_and_key_functions_callable(self) -> None:
        """_legacy.py still compiles and key functions work after deletion."""
        from app.services._legacy import (
            connector_for, is_slow_scrape_source, source_due_for_scraping,
            audit, create_opportunity, reanalyze_opportunity,
            opportunity_status,
        )
        assert callable(connector_for)


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
