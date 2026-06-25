from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import quote

from worker.connectors.common import fetch_httpx_text
from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


CORDIS_API_URL = (
    "https://cordis.europa.eu/api/search/results"
    "?q=contenttype%3D%27project%27%20AND%20frameworkProgramme%3D%27H2020%27"
    "&p={page}&num=50&format=json&srt=%2FlastUpdateDate%3Adecreasing"
)
CORDIS_PROJECT_URL = "https://cordis.europa.eu/project/id/{reference}"


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_cordis_date(value: str | None) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    template_match = re.search(r"(\d{1,2})\s*\{\{month_(\d{2})\}\}\s*(\d{4})", text)
    if template_match:
        day, month, year = int(template_match.group(1)), int(template_match.group(2)), int(template_match.group(3))
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _is_recent_or_active(item: dict[str, object], *, now: datetime) -> bool:
    end_date = _parse_cordis_date(str(item.get("endDate") or ""))
    if end_date and end_date.date() >= now.date():
        return True
    updated = _parse_cordis_date(str(item.get("lastUpdateDate") or ""))
    if updated and (now - updated).days <= 540:
        return True
    return False


class CordisH2020Connector:
    source_key = "cordis-h2020"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or CORDIS_API_URL.format(page=1)

    async def fetch(self) -> RawSourceResult:
        all_items: list[dict[str, object]] = []
        final_url = self.base_url
        for page in range(1, 4):
            page_url = CORDIS_API_URL.format(page=page)
            final_url, content, _ = await fetch_httpx_text(
                page_url,
                fallback_content_type="application/json",
                playwright_fallback=False,
            )
            payload = json.loads(content)
            records = payload.get("payload", {}).get("results") or []
            if not records:
                break
            all_items.extend(item for item in records if isinstance(item, dict))
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=json.dumps(all_items, ensure_ascii=False),
            content_type="application/json",
            metadata={"items_fetched": len(all_items)},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            items = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []
        now = datetime.now(UTC).replace(tzinfo=None)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            if not _is_recent_or_active(item, now=now):
                continue
            reference = _clean(str(item.get("reference") or item.get("id") or ""))
            title = _clean(str(item.get("title") or item.get("acronym") or ""))
            if not reference or not title or reference in seen:
                continue
            seen.add(reference)
            acronym = _clean(str(item.get("acronym") or ""))
            programme = ""
            programmes = item.get("programme")
            if isinstance(programmes, list) and programmes:
                first = programmes[0]
                if isinstance(first, dict):
                    programme = _clean(str(first.get("title") or first.get("code") or ""))
            summary_parts = [part for part in (acronym, programme, _clean(str(item.get("teaser") or ""))) if part]
            summary = " — ".join(summary_parts) or title
            open_date = _parse_cordis_date(str(item.get("startDate") or ""))
            close_date = _parse_cordis_date(str(item.get("endDate") or ""))
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="Horizon 2020",
                    country="European Union",
                    official_url=CORDIS_PROJECT_URL.format(reference=quote(reference)),
                    summary=summary[:700],
                    categories=["grants", "research", "innovation", "horizon 2020"],
                    topics=[acronym or "H2020", programme][:2],
                    raw_text=summary[:2500],
                    confidence_score=0.68,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return candidates[:60]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and "cordis.europa.eu/project/id/" in candidate.official_url))
