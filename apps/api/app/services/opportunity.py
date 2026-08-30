"""Opportunity lifecycle, enrichment, and AI extraction helpers.

Extracted from ``_legacy.py`` (PR C-2a). Provides the core opportunity
CRUD path — create, update, enrich via AI, parse funding/close dates,
and text summarization.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.ai import (
    build_local_extraction,
    extract_opportunity_structured,
    infer_language,
    summarize_opportunity_text,
)
from app.core.config import get_settings
from app.models import (
    Opportunity,
    OpportunityStatus,
    OrganizationProfile,
)
from app.schemas import OpportunityCreate
from app.services.dedup import (
    _organization_opportunity_scope,
    find_duplicate_opportunity,
)

# bulk dedup cache: external_id -> Opportunity per source (preloaded 1 query/source)
_BULK_EXTERNAL_CACHE: dict[str, set[str]] = {}
_EMBEDDING_HASH_CACHE: dict[str, list[float]] = {}
from app.services.embeddings import (
    opportunity_reanalysis_text,
    upsert_opportunity_embedding,
)
from app.services.scoring import calculate_score
from app.services.validation import async_url_is_reachable, is_noise_payload, slugify, url_is_reachable


def _parse_ai_close_date(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_tr_artifact(raw: str | None) -> bool:
    if not raw:
        return False
    s = raw.strip().lower()
    return s in {"tr", "td", "th", "table", "tbody", "thead"}


def _parse_funding_amount(
    funding_raw: str | None,
    country: str | None = None,
    url: str | None = None,
) -> tuple[float | None, str | None]:
    """Parse ``funding_amount_raw`` into (numeric_value, currency_code).

    Handles formats like:
      - ``USD 500,000`` / ``EUR 1.2 million`` / ``COP 5000000``
      - ``$500,000`` / ``$5,000,000 COP`` / ``$1.2M``
      - ``US$ 500,000`` / ``€ 1.200.000``
      - ``5.000.000.000`` (Spanish notation, dots as thousands sep)
      - ``$980.000.000`` with COP inference for .gov.co / Colombia
      - ``18e9`` scientific notation
    Returns ``(None, None)`` when no pattern matches or when the
    extracted value looks like a non-funding number.
    """
    if not funding_raw:
        return None, None

    # F2: filter React JSON artifact "tr" (183 polluted)
    if _is_tr_artifact(funding_raw):
        return None, None

    text = funding_raw.strip()
    # also reject bare tr inside longer html artifact
    if text.strip().lower() == "tr":
        return None, None
    upper_text = text.upper()

    # Guard: require at least one digit
    if not re.search(r"\d", text):
        return None, None

    # Scientific 18e9 → expand before other parsing
    sci = re.search(r"(\d+(?:\.\d+)?)\s*[eE]\s*(\d+)", text)
    sci_value: float | None = None
    if sci:
        try:
            sci_value = float(sci.group(1)) * (10 ** int(sci.group(2)))
        except (ValueError, OverflowError):
            sci_value = None

    # Detect currency from explicit markers
    currency = None
    currency_map: list[tuple[str | None, list[str]]] = [
        ("COP", ["COP", "COL$", "COL $"]),
        ("EUR", ["EUR", "€"]),
        ("GBP", ["GBP", "£"]),
        ("BRL", ["BRL", "R$"]),
        ("MXN", ["MXN", "MX$"]),
        ("USD", ["USD", "US$"]),
    ]
    for code, symbols in currency_map:
        if any(sym in upper_text for sym in symbols):
            currency = code
            break

    # Bare $ detection (no explicit currency yet, but $ present)
    has_bare_dollar = "$" in text and currency is None

    # COP inference: bare $ in Colombia context → COP; do NOT infer USD without explicit marker
    is_co_context = False
    if country and country.strip().lower() == "colombia":
        is_co_context = True
    if url and any(dom in url.lower() for dom in [".gov.co", ".edu.co", "fondoemprender.com", "minciencias.gov.co"]):
        is_co_context = True
    if has_bare_dollar and is_co_context:
        currency = "COP"
    # bare $ without CO context and no explicit currency -> remain None (rejected by gate)

    # Normalize: remove currency symbols/text, keep digits ,.
    cleaned = re.sub(r"[^\d,.\s]", " ", text)
    # Remove scientific part already handled - avoid double count
    if sci:
        cleaned = re.sub(r"\d+(?:\.\d+)?\s*[eE]\s*\d+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Locale-aware thousands/decimal handling (CO)
    # If both . and , present: CO locale 1.234.567,50 -> 1234567.50
    # If only dots with 3-digit groups: strip dots
    if "." in cleaned and "," in cleaned:
        # Assume CO: dots are thousands, comma is decimal
        if re.search(r"\d\.\d{3}", cleaned):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", ".")
    elif re.search(r"\d\.\d{3}", cleaned):
        cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "").strip()

    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if sci_value is not None:
        # scientific is primary; combine if numbers also present take max
        if numbers:
            value = max(max(float(n) for n in numbers), sci_value)
        else:
            value = sci_value
    else:
        if not numbers:
            return None, None
        value = max(float(n) for n in numbers)

    # Handle million/k suffixes
    million_suffix = re.search(r"(?:million|MM|millón|millones)\b", text, re.IGNORECASE)
    k_suffix = re.search(r"\b[kK]\b", text)
    ends_with_m = bool(re.search(r"\d+M(?:$|\s)", text))

    if million_suffix or ends_with_m:
        value *= 1_000_000
    elif k_suffix and value < 1_000_000:
        value *= 1_000

    # ── Quality gates ──────────────────────────────────────────────
    if currency is None:
        # No currency inferred and not bare $ -> reject (avoid years etc.)
        # But if large number >= 10000 and CO context, infer COP
        if is_co_context and value >= 10_000:
            currency = "COP"
        else:
            return None, None

    # Bare $ weak signal requires >=500 (avoid years/page numbers) — for COP inference
    if currency == "COP" and has_bare_dollar and value < 500:
        return None, None
    if currency == "USD" and has_bare_dollar and not re.search(r"(?:USD|US\$)", upper_text):
        if value < 500:
            return None, None
    # If still USD via explicit marker, accept; otherwise bare $ non-CO already None via gate

    # Cap absurdly large values (> 1e12) — likely parsing error, allow up to 18e9
    if value > 1_000_000_000_000:
        return None, None

    # Infer COP default for large bare numbers without marker but CO context
    # already handled

    return value, currency


def _parse_ai_open_date(value: object) -> datetime | None:
    """Parse open_date same as close_date — reuse _parse_ai_close_date logic."""
    return _parse_ai_close_date(value)


def _combined_text(data: OpportunityCreate) -> str:
    """Build a combined text blob from all available fields for regex extraction.

    Many connectors only populate ``raw_text`` with the summary from a list
    page, which rarely contains the close date — that information lives in
    the title, description, or combined text. Merging all fields together
    gives the regex-based ``extract_close_date`` a much better chance.
    """
    return " ".join(
        part for part in [data.title, data.summary, data.description, data.raw_text] if part
    )


# ── Thin / metadata summary detection ────────────────────────────────────────

_THIN_NOISE_RE = re.compile(
    r"official website|here'?s how you know|sitemap entry|^https?://",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z ,'()/-]{2,48}:")


def is_thin_or_metadata_summary(summary: str | None) -> bool:
    """Detect summaries that carry no real descriptive content.

    Some connectors (Grants.gov, Simpler Grants) build list-page summaries
    purely from metadata ("Number: X | Agency: Y | Status: posted"). Those
    must not block AI/heuristic enrichment, and must never overwrite an
    existing substantive summary on re-scrape.
    """
    try:
        thin_threshold = int(get_settings().extraction_thin_threshold)
    except Exception:
        thin_threshold = 200
    s = (summary or "").strip()
    if len(s) < thin_threshold:
        return True
    if re.match(r"^\s*(number|opportunity\s+number|notice)\s*[:：]", s, re.IGNORECASE):
        return True
    if "| status:" in s.lower():
        return True
    # Government banner boilerplate at the start.
    if re.match(
        r"^(an official website|here'?s how you know|official websites use)",
        s,
        re.IGNORECASE,
    ):
        return True
    if s.lower().startswith(("sitemap entry", "title ", "http")):
        return True
    # Form-label dumps: several "Field: value" pairs up front.
    if len(_LABEL_RE.findall(s[:220])) >= 3:
        return True
    if _THIN_NOISE_RE.search(s[:200]) and len(re.sub(r"\s+", " ", s)) < 260:
        return True
    return False


async def enrich_opportunity_payload(data: OpportunityCreate) -> OpportunityCreate:
    raw_text = data.raw_text.strip()
    combined = _combined_text(data)
    settings = get_settings()
    # LLM 100% coverage: force LLM if close_date/funding missing even when not thin,
    # or when EXTRACTION_LLM_ALWAYS flag is set (covers thin→0 goal).
    missing_critical = (data.close_date is None and data.funding_amount_raw is None and data.open_date is None)
    force_llm_for_missing = missing_critical or bool(settings.extraction_llm_always)
    if not raw_text or len(raw_text) < 120:
        merged = data.model_dump()
        if merged.get("language") in {None, "", "auto"}:
            merged["language"] = infer_language(
                " ".join([data.title, data.summary, data.raw_text, data.description]),
                fallback="es",
            )
        # Try date extraction from combined text (extract_dates covers open+close)
        if combined:
            from app.connectors.common import extract_dates

            od, cd = extract_dates(combined)
            if not merged.get("open_date") and od:
                merged["open_date"] = od
            if not merged.get("close_date") and cd:
                merged["close_date"] = cd
        return OpportunityCreate(**merged)
    if (
        data.summary
        and not is_thin_or_metadata_summary(data.summary)
        and data.categories
        and data.requirements
        and data.confidence_score >= 0.75
        and not force_llm_for_missing
    ):
        merged = data.model_dump()
        if merged.get("language") in {None, "", "auto"}:
            merged["language"] = infer_language(
                " ".join([data.title, data.summary, data.raw_text, data.description]),
                fallback="es",
            )
        # Try date extraction from combined text even on early return
        if combined:
            from app.connectors.common import extract_dates

            od, cd = extract_dates(combined)
            if not merged.get("open_date") and od:
                merged["open_date"] = od
            if not merged.get("close_date") and cd:
                merged["close_date"] = cd
        return OpportunityCreate(**merged)
    extraction = await create_ai_extraction(raw_text)
    merged = data.model_dump()
    merged["title"] = data.title or str(extraction.get("title") or merged["title"])
    merged["entity"] = data.entity or str(extraction.get("entity") or merged["entity"])
    merged["country"] = (
        data.country
        if data.country and data.country != "Por validar"
        else str(extraction.get("country") or merged["country"])
    )
    merged["categories"] = data.categories or list(extraction.get("category") or [])
    merged["topics"] = data.topics or list(extraction.get("matched_keywords") or [])
    incoming_summary = (
        data.summary if not is_thin_or_metadata_summary(data.summary) else ""
    )
    extraction_summary = str(extraction.get("summary") or "")
    if is_thin_or_metadata_summary(extraction_summary):
        extraction_summary = ""
    merged["summary"] = (
        incoming_summary
        or extraction_summary
        # Nada sustancial todavia: conservar el fallback previo del
        # extractor (p.ej. "Resumen pendiente...") para no dejar vacio.
        or str(extraction.get("summary") or "")
        or str(merged.get("summary") or "")
    )
    merged["description"] = data.description or str(
        extraction.get("summary") or merged["description"]
    )
    merged["requirements"] = data.requirements or list(extraction.get("requirements") or [])
    merged["documents_required"] = data.documents_required or list(
        extraction.get("documents_required") or []
    )
    merged["evaluation_criteria"] = data.evaluation_criteria or list(
        extraction.get("evaluation_criteria") or []
    )
    merged["restrictions"] = data.restrictions or list(extraction.get("restrictions") or [])
    merged["risk_flags"] = data.risk_flags or list(extraction.get("risks") or [])
    merged["funding_amount_raw"] = data.funding_amount_raw or extraction.get("funding_amount_raw")
    if _is_tr_artifact(merged.get("funding_amount_raw")):
        merged["funding_amount_raw"] = None
    # Funding value/currency — prefer LLM normalized, fallback to parser
    if not data.funding_amount_value:
        # Use LLM normalized value if present and valid
        llm_val = extraction.get("funding_amount_value")
        llm_cur = extraction.get("funding_amount_currency")
        if llm_val is not None:
            try:
                merged["funding_amount_value"] = float(llm_val)
                merged["funding_amount_currency"] = str(llm_cur).upper() if llm_cur else None
            except (TypeError, ValueError):
                pass
        if not merged.get("funding_amount_value"):
            parsed_value, parsed_currency = _parse_funding_amount(
                merged["funding_amount_raw"],
                country=merged.get("country"),
                url=merged.get("official_url") or data.official_url,
            )
            if parsed_value is not None:
                merged["funding_amount_value"] = parsed_value
                merged["funding_amount_currency"] = parsed_currency
    merged["language"] = (
        data.language
        if data.language not in {"", "auto"}
        else str(extraction.get("language") or infer_language(raw_text, fallback="es"))
    )
    merged["confidence_score"] = round(
        max(
            float(data.confidence_score),
            float(extraction.get("confidence") or data.confidence_score),
        ),
        2,
    )
    merged["close_date"] = data.close_date or _parse_ai_close_date(extraction.get("close_date"))
    merged["open_date"] = data.open_date or _parse_ai_open_date(extraction.get("open_date"))
    # Fallback: try extract_dates from combined text (covers open+close, unlabeled desde...hasta)
    if combined and (not merged["close_date"] or not merged["open_date"]):
        from app.connectors.common import extract_dates

        od, cd = extract_dates(combined)
        if not merged["open_date"] and od:
            merged["open_date"] = od
        if not merged["close_date"] and cd:
            merged["close_date"] = cd
    if merged["close_date"] and merged.get("risk_flags"):
        merged["risk_flags"] = [
            flag
            for flag in merged["risk_flags"]
            if "no se detectó una fecha de cierre" not in str(flag).lower()
        ]
    # ── Post-processing: country inference + title cleanup ──────────────
    from app.connectors.common import clean_opportunity_title, infer_country_from_entity

    merged["title"] = clean_opportunity_title(merged.get("title"))
    if not merged.get("country") or merged["country"] in ("Por validar", "Sin dato", ""):
        inferred = infer_country_from_entity(
            merged.get("entity"),
            merged.get("official_url"),
        )
        if inferred and inferred != "Por validar":
            merged["country"] = inferred
    return OpportunityCreate(**merged)


async def reanalyze_opportunity(
    db: Session, opportunity: Opportunity, *, force: bool = False
) -> Opportunity:
    text = opportunity_reanalysis_text(db, opportunity)
    if not text.strip():
        return opportunity
    extraction = await create_ai_extraction(text)
    changed = False
    if force or not opportunity.summary:
        opportunity.summary = str(extraction.get("summary") or opportunity.summary)
        changed = True
    if force or not opportunity.requirements:
        opportunity.requirements = list(extraction.get("requirements") or opportunity.requirements)
        changed = True
    if force or not opportunity.documents_required:
        opportunity.documents_required = list(
            extraction.get("documents_required") or opportunity.documents_required
        )
        changed = True
    if force or not opportunity.risk_flags:
        opportunity.risk_flags = list(extraction.get("risks") or opportunity.risk_flags)
        changed = True
    if force or not opportunity.categories:
        opportunity.categories = list(extraction.get("category") or opportunity.categories)
        changed = True
    if force or not opportunity.topics:
        opportunity.topics = list(extraction.get("matched_keywords") or opportunity.topics)
        changed = True
    if force or opportunity.country == "Por validar":
        opportunity.country = str(extraction.get("country") or opportunity.country)
        changed = True
    if force or not opportunity.funding_amount_raw:
        incoming_raw = extraction.get("funding_amount_raw") or opportunity.funding_amount_raw
        if _is_tr_artifact(incoming_raw):
            incoming_raw = None
        if incoming_raw != opportunity.funding_amount_raw:
            opportunity.funding_amount_raw = incoming_raw
            changed = True
    # Funding value/currency — prefer LLM normalized
    if not opportunity.funding_amount_value:
        llm_val = extraction.get("funding_amount_value")
        llm_cur = extraction.get("funding_amount_currency")
        if llm_val is not None:
            try:
                opportunity.funding_amount_value = float(llm_val)
                opportunity.funding_amount_currency = str(llm_cur).upper() if llm_cur else None
                changed = True
            except (TypeError, ValueError):
                pass
    if opportunity.funding_amount_raw and not opportunity.funding_amount_value:
        parsed_value, parsed_currency = _parse_funding_amount(
            opportunity.funding_amount_raw,
            country=opportunity.country,
            url=opportunity.official_url,
        )
        if parsed_value is not None:
            opportunity.funding_amount_value = parsed_value
            opportunity.funding_amount_currency = parsed_currency
            changed = True
    confidence = float(extraction.get("confidence") or opportunity.confidence_score or 0.5)
    if force or confidence > opportunity.confidence_score:
        opportunity.confidence_score = round(confidence, 2)
        changed = True
    close_date = _parse_ai_close_date(extraction.get("close_date"))
    if close_date and (force or not opportunity.close_date):
        opportunity.close_date = close_date
        changed = True
    open_date = _parse_ai_open_date(extraction.get("open_date"))
    if open_date and (force or not opportunity.open_date):
        opportunity.open_date = open_date
        changed = True
    if changed:
        opportunity.status = inferred_opportunity_status(
            opportunity.close_date,
            " ".join([opportunity.summary, opportunity.raw_text]),
        )
        await upsert_opportunity_embedding(db, opportunity)
    return opportunity


def opportunity_status(close_date: datetime | None) -> str:
    if not close_date:
        return OpportunityStatus.unknown.value
    now = datetime.now(UTC).replace(tzinfo=None)
    days = get_settings().scraping_closing_soon_days
    if close_date < now:
        return OpportunityStatus.closed.value
    if close_date <= now + timedelta(days=days):
        return OpportunityStatus.closing_soon.value
    return OpportunityStatus.open.value


def inferred_opportunity_status(close_date: datetime | None, text: str = "") -> str:
    status = opportunity_status(close_date)
    if status == OpportunityStatus.unknown.value and re.search(
        r"\b(open|posted|abierta|abierto)\b", text, re.IGNORECASE
    ):
        return OpportunityStatus.open.value
    return status


def _update_opportunity(
    opportunity: Opportunity,
    data: OpportunityCreate,
    normalized_title: str,
) -> None:
    """Apply scraped data to an existing opportunity record."""
    opportunity.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
    opportunity.title = normalized_title
    opportunity.entity = data.entity
    opportunity.country = data.country
    opportunity.region = data.region
    opportunity.language = data.language
    opportunity.categories = list(data.categories)
    opportunity.topics = list(data.topics)
    opportunity.description = data.description
    if data.summary and not is_thin_or_metadata_summary(data.summary):
        # Incoming summary carries real content — adopt it.
        opportunity.summary = data.summary
    elif is_thin_or_metadata_summary(opportunity.summary or ""):
        # Both incoming and existing are thin: fall back to description.
        opportunity.summary = data.summary or data.description or opportunity.summary
    # Else: existing summary is substantive and the incoming one is thin
    # metadata (list-page rebuilds) — keep the better existing summary.
    opportunity.raw_text = data.raw_text or opportunity.raw_text
    opportunity.official_url = data.official_url
    opportunity.application_url = data.application_url
    opportunity.open_date = data.open_date
    opportunity.close_date = data.close_date
    opportunity.funding_amount_value = data.funding_amount_value
    opportunity.funding_amount_currency = data.funding_amount_currency
    opportunity.funding_amount_raw = data.funding_amount_raw
    opportunity.eligible_applicants = list(data.eligible_applicants)
    opportunity.requirements = list(data.requirements)
    opportunity.documents_required = list(data.documents_required)
    opportunity.evaluation_criteria = list(data.evaluation_criteria)
    opportunity.restrictions = list(data.restrictions)
    opportunity.risk_flags = list(data.risk_flags)
    opportunity.confidence_score = data.confidence_score
    opportunity.status = inferred_opportunity_status(
        data.close_date,
        " ".join([data.summary, data.raw_text]),
    )


async def _update_and_score(
    db: Session,
    opportunity: Opportunity,
    data: OpportunityCreate,
    normalized_title: str,
    score_org_id: str | None,
) -> Opportunity:
    """Update opportunity, recalculate embedding + score."""
    _update_opportunity(opportunity, data, normalized_title)
    actual_org_id = opportunity.organization_id or score_org_id
    await upsert_opportunity_embedding(db, opportunity)
    if actual_org_id:
        profile = db.scalar(
            select(OrganizationProfile).where(OrganizationProfile.organization_id == actual_org_id)
        )
        if profile:
            calculate_score(db, opportunity, profile)
    return opportunity


def preload_external_ids(db: Session, source_id: str) -> set[str]:
    """Bulk preload existing external_ids for a source — 1 query per source."""
    if source_id in _BULK_EXTERNAL_CACHE:
        return _BULK_EXTERNAL_CACHE[source_id]
    rows = db.scalars(select(Opportunity.external_id).where(Opportunity.source_id == source_id)).all()
    cache = {r for r in rows if r}
    _BULK_EXTERNAL_CACHE[source_id] = cache
    return cache


def clear_bulk_cache() -> None:
    _BULK_EXTERNAL_CACHE.clear()
    _EMBEDDING_HASH_CACHE.clear()


async def create_opportunity(
    db: Session,
    data: OpportunityCreate,
    organization_id: str | None = None,
) -> Opportunity:
    data = await enrich_opportunity_payload(data)
    normalized_title = data.title.strip()
    if is_noise_payload(normalized_title, data.summary, data.raw_text):
        raise ValueError("Opportunity title looks like scraping noise")
    slug = slugify(f"{normalized_title}-{data.entity}")
    score_org_id = organization_id
    if data.official_url and not await async_url_is_reachable(data.official_url):
        data = data.model_copy(update={"official_url": None})
    if data.application_url and not await async_url_is_reachable(data.application_url):
        data = data.model_copy(update={"application_url": None})

    # ── Dedup checks (ordered by specificity) ─────────────────────────────
    if data.external_id and data.source_id:
        existing = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.external_id == data.external_id,
                or_(
                    Opportunity.organization_id == organization_id,
                    Opportunity.organization_id.is_(None),
                ),
            )
        )
        if existing:
            return await _update_and_score(db, existing, data, normalized_title, score_org_id)

    if data.external_id and data.external_id.startswith("dedup-"):
        existing = db.scalar(
            select(Opportunity)
            .where(
                Opportunity.external_id == data.external_id,
                _organization_opportunity_scope(organization_id),
            )
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return await _update_and_score(db, existing, data, normalized_title, score_org_id)

    duplicate = find_duplicate_opportunity(db, data, organization_id)
    if duplicate:
        return await _update_and_score(db, duplicate, data, normalized_title, score_org_id)

    if data.source_id and data.official_url:
        existing = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.official_url == data.official_url,
                or_(
                    Opportunity.organization_id == organization_id,
                    Opportunity.organization_id.is_(None),
                ),
            )
        )
        if existing:
            return await _update_and_score(db, existing, data, normalized_title, score_org_id)

    existing = db.scalar(
        select(Opportunity).where(
            Opportunity.slug == slug,
            Opportunity.entity == data.entity,
            Opportunity.close_date == data.close_date,
        )
    )
    if existing:
        _update_opportunity(existing, data, normalized_title)
        await upsert_opportunity_embedding(db, existing)
        return existing

    # ── Create new opportunity ────────────────────────────────────────────
    values = data.model_dump()
    values.pop("title", None)
    if values.get("language") in {None, "", "auto"}:
        values["language"] = infer_language(
            " ".join([data.title, data.summary, data.raw_text, data.description]),
            fallback="es",
        )
    opportunity = Opportunity(
        **values,
        organization_id=organization_id,
        title=normalized_title,
        slug=slug,
        status=inferred_opportunity_status(
            data.close_date,
            " ".join([data.summary, data.raw_text]),
        ),
    )
    db.add(opportunity)
    db.flush()
    await upsert_opportunity_embedding(db, opportunity)
    if score_org_id:
        profile = db.scalar(
            select(OrganizationProfile).where(OrganizationProfile.organization_id == score_org_id)
        )
        if profile:
            calculate_score(db, opportunity, profile)
    return opportunity


def create_heuristic_extraction(text: str) -> dict[str, object]:
    return build_local_extraction(text)


async def create_ai_extraction(text: str) -> dict[str, object]:
    extraction = await extract_opportunity_structured(text)
    return extraction.data


def summarize_text(text: str) -> str:
    return summarize_opportunity_text(text)


def count_query(db: Session, stmt: Select[tuple[Opportunity]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
