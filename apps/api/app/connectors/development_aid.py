"""DevelopmentAid.org tender connector — sitemap-driven two-phase extraction.

Phase 1 (fetch): discover tender URLs from the sitemap index.
Phase 2 (parse): fetch individual detail pages and extract structured
metadata from Angular SSR HTML via regex patterns.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import structlog
from xml.etree import ElementTree as etree

from app.connectors.base import (
    OpportunityCandidate,
    RawSourceResult,
    ValidationResult,
)
from app.connectors.common import fetch_httpx_text
from app.connectors.registry import register

logger = structlog.get_logger(__name__)

SITEMAP_INDEX_URL = "https://www.developmentaid.org/tenders_sitemap.xml"
MAX_DETAIL_PAGES = 40

# ── Regex patterns for Angular SSR HTML extraction ─────────────────────
_RE_TITLE = re.compile(r'<h1 class="name"[^>]*>(.*?)</h1>', re.DOTALL)
_RE_LOCATION = re.compile(
    r'<span[^>]*>Location:</span>\s*.*?<span[^>]*>(.*?)</span>', re.DOTALL
)
_RE_STATUS = re.compile(
    r'<span[^>]*>Status:</span>\s*.*?<span[^>]*>(.*?)</span>', re.DOTALL
)
_RE_SECTORS = re.compile(
    r'<span[^>]*>Sectors:</span>\s*.*?<span[^>]*>(.*?)</span>', re.DOTALL
)
_RE_CATEGORY = re.compile(
    r'<span[^>]*>Category:</span>\s*.*?<span[^>]*>(.*?)</span>', re.DOTALL
)
_RE_FUNDING_AGENCY = re.compile(
    r'Funding Agency:</span>\s*.*?<a[^>]*>(.*?)</a>', re.DOTALL
)
_RE_DATE_POSTED = re.compile(
    r'<span[^>]*>Posted:</span>\s*.*?<span[^>]*>(.*?)</span>', re.DOTALL
)
_RE_EXCERPT = re.compile(
    r'class="injected-content view-excerpt[^"]*"[^>]*>(.*?)</div>', re.DOTALL
)
_RE_TENDER_ID = re.compile(r"/tenders/view/(\d+)")

# ── Helpers ────────────────────────────────────────────────────────────


def _extract_domain(url: str) -> str:
    """Return a short label for the URL (dedup hash)."""
    tender_id_match = _RE_TENDER_ID.search(url)
    if tender_id_match:
        return tender_id_match.group(0)
    return url


def _parse_sitemap_index(xml_text: str) -> list[str]:
    """Extract sub-sitemap <loc> URLs from the sitemap index XML."""
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = root.findall(".//sm:sitemap/sm:loc", ns)
        return [loc.text.strip() for loc in locs if loc.text]
    except etree.ParseError:
        logger.warning("sitemap_index_malformed")
        return []


def _parse_sitemap_entries(xml_text: str) -> list[dict[str, str]]:
    """Extract <url>/<loc> + <lastmod> from a sub-sitemap XML body.

    Returns a list of dicts with keys ``loc`` and ``lastmod``.
    Deduplicates by ``loc``.
    """
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        seen: set[str] = set()
        entries: list[dict[str, str]] = []
        for url_elem in root.findall(".//sm:url", ns):
            loc_elem = url_elem.find("sm:loc", ns)
            if loc_elem is None or not loc_elem.text:
                continue
            loc = loc_elem.text.strip()
            if loc in seen:
                continue
            seen.add(loc)
            lastmod_elem = url_elem.find("sm:lastmod", ns)
            lastmod = lastmod_elem.text.strip() if lastmod_elem is not None and lastmod_elem.text else ""
            entries.append({"loc": loc, "lastmod": lastmod})
        return entries
    except etree.ParseError as exc:
        logger.warning("sub_sitemap_malformed", error=str(exc))
        return []


def _extract_fields_from_html(
    html: str, url: str
) -> dict[str, str] | None:
    """Regex-extract structured fields from an Angular SSR detail page.

    Returns None when the required <h1 class="name"> element is missing.
    """
    title_match = _RE_TITLE.search(html)
    if not title_match:
        return None

    title = _clean_html(title_match.group(1))

    location_match = _RE_LOCATION.search(html)
    country = _clean_html(location_match.group(1)) if location_match else ""

    status_match = _RE_STATUS.search(html)
    status = _clean_html(status_match.group(1)) if status_match else ""

    sectors_match = _RE_SECTORS.search(html)
    sectors = _clean_html(sectors_match.group(1)) if sectors_match else ""

    category_match = _RE_CATEGORY.search(html)
    category = _clean_html(category_match.group(1)) if category_match else ""

    funding_match = _RE_FUNDING_AGENCY.search(html)
    funding_agency = _clean_html(funding_match.group(1)) if funding_match else ""

    date_match = _RE_DATE_POSTED.search(html)
    date_posted = _clean_html(date_match.group(1)) if date_match else ""

    excerpt_match = _RE_EXCERPT.search(html)
    excerpt = _clean_html(excerpt_match.group(1)) if excerpt_match else ""

    return {
        "title": title,
        "country": country,
        "status": status,
        "sectors": sectors,
        "category": category,
        "funding_agency": funding_agency,
        "date_posted": date_posted,
        "excerpt": excerpt,
    }


def _status_is_accepted(status: str) -> bool:
    """Check if the extracted status text is accepted.

    Accepted: starts with "Open" or "Forecast" (case-insensitive).
    """
    s = status.strip().lower()
    if not s:
        return False
    return s.startswith("open") or s.startswith("forecast")


def _clean_html(text: str) -> str:
    """Strip HTML tags and whitespace from extracted text."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _title_from_slug(slug: str) -> str:
    """Convert a URL slug into a human-readable title.

    ``caribbean-efficient-and-green-energy-buildings-project``
    → ``Caribbean Efficient and Green Energy Buildings Project``
    """
    return slug.replace("-", " ").strip().title()


def _parse_lastmod(value: str) -> datetime | None:
    """Parse a sitemap ``lastmod`` value into a datetime.

    Handles ISO 8601 with timezone offset (e.g. ``2026-08-20T23:59:59+02:00``).
    """
    if not value:
        return None
    # Try ISO format with timezone
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    # Try with Z suffix
    try:
        dt = datetime.strptime(value.replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


# ── Connector ──────────────────────────────────────────────────────────


@register("developmentaid-tenders")
class DevelopmentAidConnector:
    """Sitemap-driven connector for DevelopmentAid.org tenders.

    Two-phase extraction:
      1. ``fetch()`` — discovers URLs from the sitemap index.
      2. ``parse()`` — visits detail pages, extracts fields, filters
         by status, and produces ``OpportunityCandidate`` objects.

    State (``processed_urls``, ``last_sitemap_fetch``) is persisted in
    ``Source.connector_config`` via ``get_updated_config()``.
    """

    source_key = "developmentaid-tenders"

    def __init__(
        self,
        source_key: str,
        base_url: str,
        *,
        connector_config: dict | None = None,
    ) -> None:
        self.source_key = source_key
        self.base_url = base_url or SITEMAP_INDEX_URL
        # ── Restore state from previous run ──────────────────────────
        config = connector_config
        if not isinstance(config, dict):
            if config is not None:
                logger.warning(
                    "connector_config_corrupted",
                    type=type(config).__name__,
                )
            config = {}
        self._processed_urls: dict[str, str] = dict(config.get("processed_urls") or {})
        self._last_fetch: datetime | None = None
        last_fetch_str = config.get("last_sitemap_fetch")
        if last_fetch_str:
            try:
                self._last_fetch = datetime.fromisoformat(last_fetch_str)
            except (ValueError, TypeError):
                logger.warning("last_sitemap_fetch_unparseable", value=last_fetch_str)

    # ── fetch() — sitemap discovery ────────────────────────────────────

    async def fetch(self) -> RawSourceResult:
        """Discover tender URLs from the sitemap index + sub-sitemaps.

        Returns a ``RawSourceResult`` with ``metadata["urls"]`` containing
        a list of ``{"loc": ..., "lastmod": ...}`` dicts.

        If the sitemap index is blocked (Cloudflare/WAF) the method catches
        the error and returns an empty result so the connector doesn't hang
        for minutes timing out.
        """
        # 1. Fetch sitemap index with a short timeout (15s) — no Playwright
        #    fallback since it requires a browser binary that may not be
        #    installed in the deployment environment.
        try:
            _final_url, content, _ct = await fetch_httpx_text(
                self.base_url,
                fallback_content_type="text/xml",
                playwright_fallback=False,
                timeout_seconds=15,
                retries=1,
            )
        except Exception as exc:
            logger.warning("sitemap_index_failed", error=str(exc))
            return RawSourceResult(
                source_key=self.source_key,
                url=self.base_url,
                content="",
                content_type="text/plain",
                metadata={"urls": [], "error": str(exc)},
            )

        sub_sitemap_urls = _parse_sitemap_index(content)
        logger.info(
            "sitemap_index_parsed",
            sub_sitemap_count=len(sub_sitemap_urls),
        )

        # 2. Fetch each sub-sitemap and collect entries (concurrent, capped)
        all_entries: list[dict[str, str]] = []
        safe_sub_urls = sub_sitemap_urls[:20]  # max 20 sub-sitemaps

        async def _fetch_sub(sub_url: str) -> list[dict[str, str]]:
            try:
                _sub_final, sub_content, _sub_ct = await fetch_httpx_text(
                    sub_url,
                    fallback_content_type="text/xml",
                    playwright_fallback=False,
                    timeout_seconds=20,
                    retries=1,
                )
                return _parse_sitemap_entries(sub_content)
            except Exception as exc:
                logger.warning("sub_sitemap_failed", url=sub_url, error=str(exc))
                return []

        import asyncio
        sub_results = await asyncio.gather(
            *[_fetch_sub(u) for u in safe_sub_urls],
            return_exceptions=True,
        )
        for entries in sub_results:
            if isinstance(entries, list):
                all_entries.extend(entries)

        sitemap_fetch_time = datetime.now(timezone.utc).isoformat()
        return RawSourceResult(
            source_key=self.source_key,
            url=self.base_url,
            content=content,
            content_type="text/xml",
            metadata={
                "urls": all_entries,
                "sitemap_fetch_time": sitemap_fetch_time,
            },
        )

    # ── parse() — sitemap-driven extraction (no detail pages) ──────────

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        """Extract opportunities from sitemap URL metadata.

        DevelopmentAid detail pages now require authentication (403).
        This method extracts data directly from sitemap entries:
        title from URL slug, lastmod as reference date.

        Applies per-run cap (MAX_DETAIL_PAGES), skips already-processed
        URLs, and updates internal state.
        """
        urls: list[dict[str, str]] = raw.metadata.get("urls", [])
        candidates: list[OpportunityCandidate] = []

        # Filter out already-processed URLs
        unseen: list[dict[str, str]] = []
        for entry in urls:
            loc = entry["loc"]
            url_hash = hashlib.sha256(loc.encode()).hexdigest()[:16]
            if url_hash in self._processed_urls:
                continue
            unseen.append(entry)

        # Apply per-run cap
        unseen = unseen[:MAX_DETAIL_PAGES]

        if not unseen:
            logger.info("parse_no_new_urls", total=len(urls))
            return candidates

        logger.info("parse_start", unseen_count=len(unseen), total=len(urls))

        # Update last_fetch timestamp
        self._last_fetch = datetime.now(timezone.utc)

        for entry in unseen:
            loc = entry["loc"]
            lastmod = entry.get("lastmod", "")

            # Extract title from URL slug
            # /tenders/view/1685752/caribbean-efficient-and-green-energy-buildings-project-...
            slug_match = re.search(r"/tenders/view/\d+/([^/?]+)", loc)
            if not slug_match:
                continue

            title = _title_from_slug(slug_match.group(1))

            # Parse lastmod as open_date (best available date)
            open_date = _parse_lastmod(lastmod)

            # Mark as processed
            url_hash = hashlib.sha256(loc.encode()).hexdigest()[:16]
            self._processed_urls[url_hash] = loc

            candidates.append(
                OpportunityCandidate(
                    title=title,
                    entity="DevelopmentAid",
                    country="",
                    official_url=loc,
                    summary=f"Sitemap entry — lastmod: {lastmod}",
                    raw_text=loc,
                    confidence_score=0.45,
                    open_date=open_date,
                )
            )

        logger.info(
            "parse_complete",
            candidates=len(candidates),
            processed_total=len(self._processed_urls),
        )
        return candidates

    # ── validate() ─────────────────────────────────────────────────────

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        """Accept candidates with non-empty title AND non-empty official_url."""
        if not candidate.title.strip():
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url.strip():
            return ValidationResult(ok=False, reason="Missing official URL")
        return ValidationResult(ok=True)

    # ── State persistence ──────────────────────────────────────────────

    def get_updated_config(self) -> dict:
        """Return the updated connector_config dict for runner to persist."""
        return {
            "last_sitemap_fetch": (
                self._last_fetch.isoformat()
                if self._last_fetch
                else datetime.now(timezone.utc).isoformat()
            ),
            "processed_urls": dict(self._processed_urls),
        }
