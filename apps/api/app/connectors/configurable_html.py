"""Declarative HTML connector — scraper behaviour driven by JSON config.

Instead of hardcoding CSS selectors and extraction logic in Python
classes, ``ConfigurableHtmlConnector`` reads its behaviour from a
``HtmlConnectorConfig`` dataclass (serialised as ``Source.connector_config``).

This allows fixing a source by changing data, not code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.connectors import common
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult

logger = logging.getLogger(__name__)

CLOSED_KEYWORDS = (
    "closed",
    "cerrado",
    "application closed",
    "call closed",
    "closed call",
    "cierre cerrado",
)
DEEP_FETCH_LIMIT = 10
DETAIL_PAGE_TIMEOUT = 15
PAGINATION_MAX_PAGES = 10


# ── Config dataclass ─────────────────────────────────────────────────────────


@dataclass
class HtmlConnectorConfig:
    """Declarative configuration for a configurable HTML connector.

    Each selector field is a **list of CSS selectors** tried in order
    (fallback chain). The first selector that matches wins.
    """

    list_selectors: list[str]
    """CSS selectors for list items (tried in order)."""

    title_selectors: list[str]
    """CSS selectors for title *inside* a matched list item."""

    link_selectors: list[str]
    """CSS selectors for link *inside* a matched list item."""

    content_selectors: list[str]
    """CSS selectors for detail content **or** page-level content block."""

    date_labels: list[str]
    """Text labels that precede close dates (e.g. ``["Cierre:", "Deadline:"]``)."""

    pagination: dict | None = None
    """Optional pagination config.

    Supported types:
    - ``{"type": "next_link", "selector": "a.next"}`` — follows a "next" link.
    """

    detail_enrichment: bool = False
    """If True, fetch detail pages for low-confidence candidates."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HtmlConnectorConfig":
        """Parse and validate a config *dict* (e.g. from JSON API payload).

        Raises ``ValueError`` if required fields are missing or empty.
        """
        errors: list[str] = []

        for field_name in ("list_selectors", "title_selectors", "link_selectors", "content_selectors", "date_labels"):
            if field_name not in data:
                errors.append(f"Missing required field: {field_name!r}")

        if errors:
            msg = "; ".join(errors)
            raise ValueError(f"Invalid HtmlConnectorConfig: {msg}")

        raw = dict(data)

        # Validate each selector list is a non-empty list of strings
        for field_name in ("list_selectors", "title_selectors", "link_selectors", "content_selectors", "date_labels"):
            val = raw[field_name]
            if not isinstance(val, list):
                raise ValueError(f"Field {field_name!r} must be a list, got {type(val).__name__}")
            if not val:
                raise ValueError(f"Field {field_name!r} must have at least one entry")

        pagination = raw.get("pagination")
        if pagination is not None and not isinstance(pagination, dict):
            raise ValueError(f"Field 'pagination' must be a dict or None, got {type(pagination).__name__}")

        return cls(
            list_selectors=list(raw["list_selectors"]),
            title_selectors=list(raw["title_selectors"]),
            link_selectors=list(raw["link_selectors"]),
            content_selectors=list(raw["content_selectors"]),
            date_labels=list(raw["date_labels"]),
            pagination=pagination,
            detail_enrichment=bool(raw.get("detail_enrichment", False)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "HtmlConnectorConfig":
        """Parse config from a JSON string.

        Raises ``ValueError`` if the JSON is invalid.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid HtmlConnectorConfig JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("HtmlConnectorConfig JSON must be a JSON object")
        return cls.from_dict(data)


# ── Connector class ──────────────────────────────────────────────────────────


class ConfigurableHtmlConnector:
    """Scraper that reads its behaviour from ``HtmlConnectorConfig``.

    Designed to be interchangeable with ``GenericHtmlConnector`` —
    implements the ``SourceConnector`` protocol (``fetch``, ``parse``,
    ``validate``).
    """

    def __init__(
        self,
        source_key: str,
        base_url: str,
        config: dict | HtmlConnectorConfig,
        *,
        entity_name: str | None = None,
        default_country: str | None = None,
        default_categories: list[str] | None = None,
    ) -> None:
        self.source_key = source_key
        self.base_url = base_url
        self._entity_name = entity_name or source_key
        self._default_country = default_country or "Por validar"
        self._default_categories = default_categories or []

        # Normalise config
        if isinstance(config, HtmlConnectorConfig):
            self.config: HtmlConnectorConfig = config
        elif isinstance(config, dict):
            self.config = HtmlConnectorConfig.from_dict(config)
        else:
            raise TypeError(f"config must be a dict or HtmlConnectorConfig, got {type(config).__name__}")

        # Diagnostics: tracks which selectors succeeded / failed per run
        self._selector_diagnostics: dict[str, str | None] = {
            "list_selector": None,
            "title_selector": None,
            "link_selector": None,
        }

    @property
    def selector_diagnostics(self) -> dict[str, str | None]:
        """Return a copy of the selector diagnostics.

        Keys: ``list_selector``, ``title_selector``, ``link_selector`` —
        values are the CSS selector string that matched, or ``None`` if
        none matched.
        """
        return dict(self._selector_diagnostics)

    # ── SourceConnector protocol ─────────────────────────────────────────

    async def fetch(self) -> RawSourceResult:
        """Fetch the source URL and return raw content."""
        final_url, content, content_type = await common.fetch_httpx_text(
            self.base_url,
            fallback_content_type="text/html",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        """Parse raw HTML content into opportunity candidates.

        Extraction order:
        1. Embedded JSON (JSON-LD, ``__NEXT_DATA__``) — highest confidence.
        2. CSS selectors from ``self.config`` (fallback chain).
        3. Detail page enrichment for low-confidence candidates.
        4. Pagination (follow next links when configured).
        """
        # ── Step 1: embedded JSON extraction ──────────────────────────
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen_urls: set[str] = set()

        embedded = self._collect_embedded_json(tree, raw.url)
        for item in embedded:
            title = str(item.get("name") or item.get("title") or item.get("headline") or "").strip()
            link = str(item.get("url") or item.get("link") or item.get("official_url") or "").strip()
            if link and not link.startswith(("http://", "https://")):
                link = urljoin(raw.url, link)
            if not title or not link or link in seen_urls:
                continue
            seen_urls.add(link)
            summary = str(item.get("description") or item.get("summary") or title).strip()
            close_date = self._candidate_close_date(item, summary)
            raw_text = summary[:2500]
            if self._is_closed(title, summary, raw_text, close_date):
                continue
            candidates.append(OpportunityCandidate(
                title=title[:180],
                entity=str(item.get("entity") or self._entity_name),
                country=str(item.get("country") or self._default_country),
                official_url=link,
                summary=summary[:700] or title,
                categories=[str(v) for v in (item.get("categories") or [])[:4] if isinstance(v, str)],
                raw_text=raw_text,
                confidence_score=0.72,
                close_date=close_date,
            ))

        # ── Step 2: CSS selector extraction ───────────────────────────
        html_candidates = self._extract_from_css(tree, raw.url, seen_urls)
        candidates.extend(html_candidates)

        # ── Step 3: pagination ────────────────────────────────────────
        if self.config.pagination and self.config.pagination.get("type") == "next_link":
            more = await self._fetch_paginated(tree, raw.url, seen_urls)
            candidates.extend(more)

        # ── Step 4: detail page enrichment ────────────────────────────
        if self.config.detail_enrichment and candidates:
            candidates = await self._deep_fetch_candidates(candidates)

        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        """Validate a candidate — basic required-field and closed check."""
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if self._is_closed(candidate.title, candidate.summary, candidate.raw_text, candidate.close_date):
            return ValidationResult(ok=False, reason="Opportunity appears closed")
        return ValidationResult(ok=True)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _collect_embedded_json(self, tree: HTMLParser, base_url: str) -> list[dict]:
        """Collect candidates from embedded JSON (JSON-LD, __NEXT_DATA__, etc.).

        Returns a list of dicts with keys: ``name``, ``url``, ``description``, …
        """
        candidates: list[dict] = []
        seen_titles: set[str] = set()
        script_selectors = [
            "script#__NEXT_DATA__",
            "script[type='application/json']",
            "script[type='application/ld+json']",
            "script",
        ]
        for selector in script_selectors:
            for script in tree.css(selector):
                content = (script.text() or "").strip()
                if not content:
                    continue
                payload = None
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError:
                    continue
                for item in self._iter_items(payload):
                    title = str(item.get("name") or item.get("title") or item.get("headline") or "").strip()
                    link = str(item.get("url") or item.get("link") or item.get("official_url") or "").strip()
                    if title and link and title not in seen_titles:
                        seen_titles.add(title)
                        candidates.append(item)
        return candidates

    def _iter_items(self, payload: object, _depth: int = 0) -> list[dict]:
        """Recursively extract dict items from a parsed JSON payload."""
        if _depth > 5:
            return []
        if isinstance(payload, list):
            items: list[dict] = []
            for item in payload:
                if isinstance(item, dict):
                    items.append(item)
                else:
                    nested = self._maybe_load_json(item)
                    if nested is not None:
                        items.extend(self._iter_items(nested, _depth + 1))
            return items
        if not isinstance(payload, dict):
            nested = self._maybe_load_json(payload)
            return self._iter_items(nested, _depth + 1) if nested is not None else []
        if any(payload.get(field) for field in ("title", "name", "url", "link", "official_url")):
            return [payload]
        items: list[dict] = []
        for key in ("items", "results", "data", "opportunities", "records", "content", "itemListElement", "@graph", "graph", "grants"):
            value = payload.get(key)
            parsed = self._maybe_load_json(value)
            if parsed is not None:
                value = parsed
            if isinstance(value, list):
                items.extend(self._iter_items(value, _depth + 1))
            elif isinstance(value, dict):
                items.extend(self._iter_items(value, _depth + 1))
        if not items:
            for value in payload.values():
                parsed = self._maybe_load_json(value)
                if parsed is not None:
                    value = parsed
                if isinstance(value, list):
                    items.extend(self._iter_items(value, _depth + 1))
                elif isinstance(value, dict):
                    items.extend(self._iter_items(value, _depth + 1))
        return items

    @staticmethod
    def _maybe_load_json(value: object) -> dict | list | None:
        """Try to parse a string value as JSON."""
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _extract_from_css(
        self,
        tree: HTMLParser,
        base_url: str,
        seen_urls: set[str],
    ) -> list[OpportunityCandidate]:
        """Extract candidates using CSS selector chain from config."""
        candidates: list[OpportunityCandidate] = []

        # Try each list selector in order
        matched_list_selector: str | None = None
        matched_items: list[Any] = []
        for selector in self.config.list_selectors:
            items = tree.css(selector)
            if items:
                matched_list_selector = selector
                matched_items = items
                break

        self._selector_diagnostics["list_selector"] = matched_list_selector
        if not matched_items:
            return []

        for container in matched_items:
            candidate = self._extract_candidate(container, base_url, seen_urls)
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def _extract_candidate(
        self,
        container: Any,
        base_url: str,
        seen_urls: set[str],
    ) -> OpportunityCandidate | None:
        """Extract a single candidate from a matched container element."""
        # ── Title (fallback chain) ────────────────────────────────────
        title: str | None = None
        title_selector_used: str | None = None
        for selector in self.config.title_selectors:
            el = container.css_first(selector)
            if el:
                text = common.clean_text(el.text())
                if text:
                    title = text
                    title_selector_used = selector
                    break
        self._selector_diagnostics["title_selector"] = title_selector_used
        if not title:
            return None

        # ── Link (fallback chain) ─────────────────────────────────────
        link: str | None = None
        link_selector_used: str | None = None
        for selector in self.config.link_selectors:
            el = container.css_first(selector)
            if el:
                href = el.attributes.get("href")
                if href:
                    link = urljoin(base_url, href)
                    link_selector_used = selector
                    break
        self._selector_diagnostics["link_selector"] = link_selector_used
        if not link:
            return None

        # Deduplicate
        if link in seen_urls:
            return None
        seen_urls.add(link)

        # ── Text content ──────────────────────────────────────────────
        text = common.clean_text(container.text())
        lowered = f"{title} {text}".lower()

        if common.looks_like_noise_text(title) or common.looks_like_noise_text(text):
            return None

        # ── Close date ────────────────────────────────────────────────
        close_date = common.extract_close_date(text)

        # ── Closed check ──────────────────────────────────────────────
        if self._is_closed(title, text, text[:2500], close_date):
            return None

        return OpportunityCandidate(
            title=title[:180],
            entity=self._entity_name,
            country=self._default_country,
            official_url=link,
            summary=text[:700] or title,
            raw_text=text[:2500],
            confidence_score=0.55,
            close_date=close_date,
        )

    def _candidate_close_date(self, item: dict, text: str | None = None) -> datetime | None:
        """Extract a close date from a dict item (embedded JSON)."""
        DATE_FIELDS = (
            "close_date",
            "closeDate",
            "deadline",
            "deadlineDate",
            "deadline_date",
            "closing_date",
            "closingDate",
            "endDate",
            "dueDate",
            "application_deadline",
        )
        for key in DATE_FIELDS:
            value = item.get(key)
            if isinstance(value, list):
                for entry in value:
                    parsed = common.parse_date_text(str(entry))
                    if parsed:
                        return parsed
            elif isinstance(value, dict):
                for nested_key in ("value", "date", "content"):
                    nested_value = value.get(nested_key)
                    if nested_value:
                        parsed = common.parse_date_text(str(nested_value))
                        if parsed:
                            return parsed
            elif value:
                parsed = common.parse_date_text(str(value))
                if parsed:
                    return parsed
        return common.parse_date_text(text)

    def _is_closed(self, title: str, summary: str, raw_text: str, close_date: datetime | None) -> bool:
        """Check if an opportunity appears closed."""
        if close_date and close_date.date() < datetime.now(UTC).date():
            return True
        normalized = f"{title} {summary} {raw_text}".lower()
        return any(keyword in normalized for keyword in CLOSED_KEYWORDS)

    # ── Pagination ────────────────────────────────────────────────────

    async def _fetch_paginated(
        self,
        tree: HTMLParser,
        base_url: str,
        seen_urls: set[str],
    ) -> list[OpportunityCandidate]:
        """Follow ``next_link`` pagination and collect additional candidates."""
        pagination = self.config.pagination
        if not pagination:
            return []

        pag_type = pagination.get("type")
        if pag_type != "next_link":
            logger.warning("Unsupported pagination type: %s", pag_type)
            return []

        selector = pagination.get("selector", "a.next")
        all_candidates: list[OpportunityCandidate] = []
        visited: set[str] = {base_url}
        current_url: str | None = base_url

        for _ in range(PAGINATION_MAX_PAGES):
            next_link = self._find_next_link(tree, selector)
            if not next_link:
                break

            next_url = urljoin(base_url, next_link)
            if next_url in visited:
                break
            visited.add(next_url)

            current_url = next_url
            try:
                final_url, content, _content_type = await common.fetch_httpx_text(
                    next_url,
                    fallback_content_type="text/html",
                )
            except Exception:
                logger.exception("Failed to fetch pagination page: %s", next_url)
                break

            page_tree = HTMLParser(content)
            candidates = self._extract_from_css(page_tree, final_url, seen_urls)
            all_candidates.extend(candidates)

            tree = page_tree  # Continue from the new page

        return all_candidates

    @staticmethod
    def _find_next_link(tree: HTMLParser, selector: str) -> str | None:
        """Find the 'next page' link in the parsed HTML tree."""
        el = tree.css_first(selector)
        if el:
            href = el.attributes.get("href")
            if href:
                return href.strip()
        return None

    # ── Detail page enrichment ────────────────────────────────────────

    async def _deep_fetch_candidates(
        self,
        candidates: list[OpportunityCandidate],
    ) -> list[OpportunityCandidate]:
        """Enrich low-confidence candidates by fetching their detail pages."""
        import asyncio

        to_enrich = [c for c in candidates if c.confidence_score < 0.7][:DEEP_FETCH_LIMIT]
        if not to_enrich:
            return candidates

        tasks = {c.official_url: self._enrich_from_detail(c.official_url) for c in to_enrich}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        url_to_data: dict[str, dict | None] = {}
        for url, task in zip(tasks, results):
            url_to_data[url] = task if isinstance(task, dict) else None

        enriched: list[OpportunityCandidate] = []
        for c in candidates:
            detail = url_to_data.get(c.official_url)
            if detail:
                enriched.append(OpportunityCandidate(
                    title=(detail.get("title") or c.title)[:180],
                    entity=c.entity,
                    country=c.country,
                    official_url=c.official_url,
                    summary=(detail.get("summary") or c.summary)[:700],
                    categories=detail.get("categories", c.categories or self._default_categories),
                    raw_text=c.raw_text,
                    confidence_score=0.82,
                    close_date=detail.get("close_date") or c.close_date,
                    funding_amount_raw=detail.get("funding_amount_raw") or c.funding_amount_raw,
                ))
            else:
                enriched.append(c)
        return enriched

    async def _enrich_from_detail(self, url: str) -> dict | None:
        """Fetch a detail page and extract structured data."""
        try:
            _, content, content_type = await common.fetch_httpx_text(
                url,
                timeout_seconds=DETAIL_PAGE_TIMEOUT,
                retries=1,
            )
        except Exception:
            return None

        result: dict = {}

        # 1. JSON-LD
        tree = HTMLParser(content)
        for script in tree.css("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.text() or "{}")
            except json.JSONDecodeError:
                continue
            for item in self._iter_items(payload):
                title = str(item.get("name") or item.get("title") or "").strip()
                if title:
                    result["title"] = title
                desc = str(item.get("description") or item.get("summary") or "").strip()
                if desc:
                    result["summary"] = desc
                cd = self._candidate_close_date(item)
                if cd:
                    result["close_date"] = cd
                cats = [str(v) for v in (item.get("categories") or [])[:4] if isinstance(v, str)]
                if cats:
                    result["categories"] = cats
                break

        # 2. Meta / OG tags
        og_title = tree.css_first("meta[property='og:title']")
        if og_title and "title" not in result:
            value = (og_title.attributes.get("content") or "").strip()
            if value:
                result["title"] = value
        og_desc = tree.css_first("meta[property='og:description']")
        if og_desc and "summary" not in result:
            value = (og_desc.attributes.get("content") or "").strip()
            if value:
                result["summary"] = value
        meta_desc = tree.css_first("meta[name='description']")
        if meta_desc and "summary" not in result:
            value = (meta_desc.attributes.get("content") or "").strip()
            if value:
                result["summary"] = value

        # 3. h1 fallback for title
        if "title" not in result:
            h1 = tree.css_first("h1")
            if h1:
                value = common.clean_text(h1.text())
                if value:
                    result["title"] = value

        # 4. Article / main content for summary
        if "summary" not in result:
            for tag in ("article", "[role='main']", "main", ".content", "#content"):
                el = tree.css_first(tag)
                if el:
                    value = common.clean_text(el.text())[:700]
                    if value:
                        result["summary"] = value
                        break

        # 5. Date from body text
        if "close_date" not in result:
            body = tree.css_first("body")
            if body:
                all_text = common.clean_text(body.text())
                cd = common.extract_close_date(all_text)
                if cd:
                    result["close_date"] = cd

        return result if result.get("title") else None
