"""Facade for ``app.services`` — backward-compatible re-exports.

All existing ``from app.services import X`` continue to work.
Extracted functions shadow the legacy implementations from their
respective single-responsibility modules.
"""

from __future__ import annotations

# ── Legacy functions (still in _legacy.py, not yet extracted) ────────────────
from app.services._legacy import (  # noqa: F401
    # Scraping / sources
    SLOW_SCRAPE_SOURCE_KEYS,
    SLOW_SCRAPE_SOURCE_TYPES,
    _scrape_source_candidates,
    _scrape_source_candidates_with_timeout,
    connector_for,
    create_source_health_alert,
    execute_source_run_locally,
    is_slow_scrape_source,
    source_due_for_scraping,
    validate_source_url,
    # Audit / alerts
    _source_health_status,
    audit,
    # Opportunity lifecycle
    _combined_text,
    _parse_ai_close_date,
    _parse_funding_amount,
    create_opportunity,
    enrich_opportunity_payload,
    inferred_opportunity_status,
    opportunity_status,
    reanalyze_opportunity,
    # AI extraction helpers
    create_ai_extraction,
    create_heuristic_extraction,
    summarize_text,
    # Query / count
    build_opportunity_query,
    count_query,
    # Triage / dashboard helpers (PR B-1a)
    _STATUS_LABELS,
    _triage_days_to_close,
    extract_score_reasons,
    get_closing_soon_7d,
    get_review_queue,
    # Pipeline helpers (PR B-1b)
    _pipeline_days_to_close,
    get_closing_soon,
    get_top_scored,
    # Health helpers (PR B-1c)
    get_data_coverage,
    get_health_kpis,
    get_sources_health,
    get_source_health_summaries,
    get_status_breakdown,
    get_country_breakdown,
    # Analytics helpers
    _backfill_close_date_text,
    _opportunity_combined_text,
    backfill_close_dates,
    backfill_close_dates_ai,
    backfill_funding_amounts,
    backfill_funding_amounts_ai,
    get_category_distribution,
    get_funding_ranges,
    get_opportunities_timeline,
    get_score_distribution,
    get_source_contribution,
    # GenAI helpers
    build_weekly_digest_html,
    rescore_all_opportunities,
    score_unscored_opportunities,
    send_weekly_digest,
    summarize_missing_opportunities,
)

# ── validation.py — pure validation functions ────────────────────────────────
from app.services.validation import (  # noqa: F401
    is_noise_payload,
    is_noise_title,
    is_private_url,
    is_public_http_url,
    normalize_official_url,
    slugify,
    url_is_reachable,
    validate_source_url,
)

# ── dedup.py — deduplication logic ───────────────────────────────────────────
from app.services.dedup import (  # noqa: F401
    _merge_opportunity_records,
    _normalize_survivor_datetime,
    _opportunity_survivor_key,
    _organization_opportunity_scope,
    _reassign_opportunity_relations,
    candidate_external_id,
    deduplicate_opportunities,
    find_duplicate_opportunity,
    opportunity_dedup_key,
)

# ── scoring.py — opportunity scoring ─────────────────────────────────────────
from app.services.scoring import (  # noqa: F401
    _compute_score,
    _semantic_score,
    calculate_score,
    priority_for_score,
)

# ── export.py — CSV / XLSX / PDF / HTML export ──────────────────────────────
from app.services.export import (  # noqa: F401
    _render_pdf_with_playwright,
    export_csv,
    export_pdf,
    export_xlsx,
    generate_report_html,
)

# ── search.py — semantic + lexical search ────────────────────────────────────
from app.services.search import (  # noqa: F401
    _lexical_search_score,
    _text_search_opportunities,
    semantic_search_opportunities,
    build_opportunity_query,
)

# ── embeddings.py — embedding management ─────────────────────────────────────
from app.services.embeddings import (  # noqa: F401
    _get_opportunity_embedding,
    _supports_vector_search,
    opportunity_embedding_text,
    opportunity_reanalysis_text,
    rebuild_opportunity_embeddings,
    upsert_opportunity_embedding,
)
