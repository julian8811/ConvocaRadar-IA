from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from app.core.config import get_settings
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, is_allowed_host, parse_date_text


def _clean(value: str | None) -> str:
    return clean_text(html.unescape(value or ""))


def _rendered_text(value: object) -> str:
    if isinstance(value, dict):
        return _clean(str(value.get("rendered") or ""))
    return _clean(str(value or ""))


def _acf_text(acf: object, *keys: str) -> str | None:
    if not isinstance(acf, dict):
        return None
    for key in keys:
        value = acf.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            rendered = _clean(str(value.get("rendered") or ""))
            if rendered:
                return rendered
        text = _clean(str(value))
        if text:
            return text
    return None


def _parse_wp_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            parsed = datetime.strptime(value[:26], fmt)
            return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
        except ValueError:
            continue
    return parse_date_text(value)


def _with_page(url: str, page: int, *, per_page: int = 100) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page)]
    query["per_page"] = [str(per_page)]
    if "status" not in query:
        query["status"] = ["publish"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


class WordPressGrantsConnector:
    source_key: str
    entity_name: str
    default_country: str
    allowed_domains: list[str]

    def __init__(
        self,
        source_key: str,
        base_url: str,
        *,
        entity_name: str | None = None,
        default_country: str = "Por validar",
        allowed_domains: list[str] | None = None,
    ) -> None:
        self.source_key = source_key
        self.base_url = base_url
        self.entity_name = entity_name or source_key
        self.default_country = default_country
        parsed = urlparse(base_url)
        hostname = parsed.hostname or ""
        self.allowed_domains = allowed_domains or ([hostname] if hostname else [])

    async def fetch(self) -> RawSourceResult:
        settings = get_settings()
        headers = {"User-Agent": settings.scraping_user_agent}
        all_items: list[dict[str, object]] = []
        final_url = self.base_url
        total_pages = 1
        async with httpx.AsyncClient(timeout=settings.scraping_timeout_seconds, headers=headers, follow_redirects=True) as client:
            for page in range(1, 51):
                page_url = _with_page(self.base_url, page)
                response = await client.get(page_url)
                response.raise_for_status()
                final_url = str(response.url)
                if page == 1:
                    total_pages = int(response.headers.get("X-WP-TotalPages", "1") or "1")
                payload = response.json()
                if not isinstance(payload, list) or not payload:
                    break
                all_items.extend(item for item in payload if isinstance(item, dict))
                if page >= total_pages:
                    break
        content = json.dumps(all_items, ensure_ascii=False)
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type="application/json",
            metadata={"pages_fetched": min(total_pages, 50), "items_fetched": len(all_items)},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "publish") != "publish":
                continue
            title = _rendered_text(item.get("title"))
            link = _clean(str(item.get("link") or ""))
            if not title or not link or link in seen:
                continue
            seen.add(link)
            acf = item.get("acf") or {}
            summary = _acf_text(acf, "summary", "description", "excerpt", "intro") or title
            deadline_raw = _acf_text(acf, "deadline", "application_deadline", "closing_date", "close_date")
            close_date = _parse_wp_date(deadline_raw) if deadline_raw else None
            open_date = _parse_wp_date(str(item.get("date") or ""))
            status_text = (_acf_text(acf, "status", "grant_status") or "").lower()
            if status_text and any(token in status_text for token in ("closed", "cerrad", "archiv")):
                continue
            if close_date and close_date.date() < datetime.now(UTC).date():
                continue
            categories = ["grants", "research", "health"]
            topics = [value for value in (_acf_text(acf, "program", "theme") or "",) if value]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self.entity_name,
                    country=self.default_country,
                    official_url=link,
                    summary=summary[:700],
                    categories=categories[:5],
                    topics=topics[:5],
                    raw_text=summary[:2500],
                    confidence_score=0.72,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return candidates[:200]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="missing title or url")
        if self.allowed_domains and not is_allowed_host(candidate.official_url, self.allowed_domains):
            return ValidationResult(ok=False, reason="domain not allowed")
        return ValidationResult(ok=True)
