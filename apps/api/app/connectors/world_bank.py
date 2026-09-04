"""World Bank procurement API connector.

The World Bank procurement page is JS-rendered, but a public JSON API is
available at https://search.worldbank.org/api/v2/procnotices.
"""

from __future__ import annotations

import json
from datetime import datetime

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import (
    clean_text,
    fetch_httpx_text,
    is_safe_candidate_snippet,
    thin_fill_candidates,
)
from app.connectors.registry import register

WORLD_BANK_API_URL = "https://search.worldbank.org/api/v2/procnotices"
WORLD_BANK_DETAIL_URL = (
    "https://projects.worldbank.org/en/projects-operations/procurement-detail/{id}"
)
_NOTICE_TEXT_CAP = 3000


def _parse_wb_date(value: str | None) -> datetime | None:
    """Parse World Bank ISO date string (e.g. '2026-08-15T00:00:00')."""
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _strip_notice_html(notice_text: str) -> str:
    """Strip HTML tags from notice_text for description/raw_text."""
    if not notice_text:
        return ""
    if "<" in notice_text:
        return clean_text(HTMLParser(notice_text).text())
    return clean_text(notice_text)


def _topic_values(item: dict) -> list[str]:
    topics: list[str] = []
    for key in ("project_id", "bid_reference_no", "procurement_method_code"):
        value = str(item.get(key) or "").strip()
        if value and value not in topics:
            topics.append(value)
    return topics


def _category_values(item: dict) -> list[str]:
    categories: list[str] = []
    for key in ("notice_type", "procurement_group", "procurement_method_name"):
        value = str(item.get(key) or "").strip()
        if value and value not in categories:
            categories.append(value)
    return categories


@register("world-bank-procurement")
class WorldBankConnector:
    source_key = "world-bank-procurement"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or WORLD_BANK_API_URL

    async def fetch(self) -> RawSourceResult:
        url = f"{self.base_url}?format=json&rows=100&srt=submission_date desc&order=desc"
        final_url, content, content_type = await fetch_httpx_text(
            url,
            fallback_content_type="application/json",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if not raw.content.lstrip().startswith("{"):
            return []
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError:
            return []

        procnotices = payload.get("procnotices") or {}
        candidates: list[OpportunityCandidate] = []

        for item_id, item in procnotices.items():
            bid_description = str(item.get("bid_description") or "").strip()
            if not bid_description:
                continue

            title = bid_description[:180]
            notice_id = str(item.get("id") or item_id).strip()

            # Prefer submission_deadline_date; fall back to submission_date.
            close_date = _parse_wb_date(item.get("submission_deadline_date")) or _parse_wb_date(
                item.get("submission_date")
            )
            open_date = _parse_wb_date(item.get("noticedate"))

            official_url = WORLD_BANK_DETAIL_URL.format(id=notice_id)
            country = str(item.get("project_ctry_name") or "International").strip()
            project_name = str(item.get("project_name") or "").strip()
            notice_text = str(item.get("notice_text") or "").strip()
            stripped = _strip_notice_html(notice_text)[:_NOTICE_TEXT_CAP] if notice_text else ""

            snippet_html: str | None = None
            if notice_text and "<" in notice_text:
                if is_safe_candidate_snippet(notice_text, official_url):
                    snippet_html = notice_text

            candidates.append(
                OpportunityCandidate(
                    title=title,
                    entity="World Bank",
                    country=country,
                    official_url=official_url,
                    summary=project_name or title,
                    description=stripped,
                    categories=_category_values(item),
                    topics=_topic_values(item),
                    raw_text=stripped,
                    confidence_score=0.85,
                    open_date=open_date,
                    close_date=close_date,
                    external_id=notice_id or None,
                    snippet_html=snippet_html,
                )
            )

        return thin_fill_candidates(candidates)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title:
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url or "worldbank.org" not in candidate.official_url:
            return ValidationResult(ok=False, reason="Missing or unexpected official URL")
        return ValidationResult(ok=True)
