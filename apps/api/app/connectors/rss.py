from datetime import datetime
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET

from app.connectors.common import clean_text, fetch_httpx_text, safe_urljoin
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None)


class RssConnector:
    def __init__(
        self,
        source_key: str,
        base_url: str,
        *,
        entity: str | None = None,
        country: str = "Por validar",
        categories: list[str] | None = None,
        topics: list[str] | None = None,
        confidence_score: float = 0.58,
    ) -> None:
        self.source_key = source_key
        self.base_url = base_url
        self.entity = entity or source_key
        self.country = country
        self.categories = categories or ["rss"]
        self.topics = topics or []
        self.confidence_score = confidence_score

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="application/rss+xml")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        root = ET.fromstring(raw.content)
        namespace = "{http://www.w3.org/2005/Atom}"
        items = root.findall(".//item") or root.findall(f".//{namespace}entry")
        candidates: list[OpportunityCandidate] = []
        for item in items:
            title = clean_text(item.findtext("title"))
            link = clean_text(item.findtext("link"))
            if not link:
                link_element = item.find(f"{namespace}link")
                if link_element is not None:
                    link = clean_text(link_element.attrib.get("href"))
            description = clean_text(
                item.findtext("description")
                or item.findtext(f"{namespace}summary")
                or item.findtext(f"{namespace}content")
                or item.findtext("summary")
                or item.findtext("content")
            )
            category = clean_text(item.findtext("category"))
            pub_date = _parse_pub_date(item.findtext("pubDate") or item.findtext(f"{namespace}updated") or item.findtext(f"{namespace}published"))
            if not title or not link:
                continue
            categories = list(dict.fromkeys([*self.categories, category.lower() if category else ""]))
            categories = [value for value in categories if value]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self.entity,
                    country=self.country,
                    official_url=safe_urljoin(raw.url, link),
                    summary=description or title,
                    categories=categories,
                    topics=[*self.topics, category] if category else self.topics[:],
                    raw_text=ET.tostring(item, encoding="unicode"),
                    confidence_score=self.confidence_score,
                    open_date=pub_date,
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or link")
        if not candidate.official_url.startswith(("http://", "https://")):
            return ValidationResult(ok=False, reason="RSS item link is not absolute")
        return ValidationResult(ok=True)
