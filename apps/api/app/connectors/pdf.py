from __future__ import annotations

import io
import re
from datetime import datetime

from pypdf import PdfReader

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import fetch_httpx_bytes, normalize_text


COUNTRY_RULES: list[tuple[str, str]] = [
    ("colombia", "Colombia"),
    ("mexico", "Mexico"),
    ("chile", "Chile"),
    ("peru", "Peru"),
    ("argentina", "Argentina"),
    ("brazil", "Brazil"),
    ("spain", "Spain"),
    ("european union", "European Union"),
    ("united states", "United States"),
    ("usa", "United States"),
]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_country(text: str) -> str:
    lowered = normalize_text(text)
    for needle, country in COUNTRY_RULES:
        if needle in lowered:
            return country
    return "Por validar"


def _extract_amount(text: str) -> str | None:
    patterns = [
        r"USD\s?[\d.,]+(?:\s?(?:million|m|k))?",
        r"EUR\s?[\d.,]+(?:\s?(?:million|m|k))?",
        r"COP\s?[\d.,]+",
        r"\$\s?[\d.,]+(?:\s?(?:COP|USD|EUR))?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_text(match.group(0))
    return None


def _extract_date(text: str) -> datetime | None:
    normalized = normalize_text(text)
    patterns = [
        (r"\b(\d{4}-\d{2}-\d{2})\b", ("%Y-%m-%d",)),
        (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", ("%m/%d/%Y", "%d/%m/%Y")),
        (r"\b([a-z]+ \d{1,2}, \d{4})\b", ("%B %d, %Y", "%b %d, %Y")),
    ]
    for pattern, formats in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        value = match.group(1)
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _split_sections(text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in (line.strip(" \t-•") for line in text.splitlines()):
        if not line:
            continue
        normalized = normalize_text(line)
        words = len(line.split())
        looks_like_title = (
            2 <= words <= 12
            and len(line) <= 120
            and not line.endswith(".")
            and (
                re.match(r"^(call|convocatoria|grant|funding|opportunity|scholarship|beca|program)", normalized)
                or ("call" in normalized and any(char.isdigit() for char in normalized))
                or (any(char.isdigit() for char in normalized) and any(keyword in normalized for keyword in ("grant", "fund", "award", "opportunity", "scholarship", "program", "convocatoria", "beca")))
            )
        )
        if len(current) >= 8 or (current and looks_like_title):
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections


class PdfConnector:
    def __init__(self, source_key: str, base_url: str) -> None:
        self.source_key = source_key
        self.base_url = base_url

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_bytes(self.base_url, fallback_content_type="application/pdf")
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content.decode("latin-1", errors="ignore"), content_type=content_type)

    def _extract_text(self, raw: RawSourceResult) -> str:
        reader = PdfReader(io.BytesIO(raw.content.encode("latin-1", errors="ignore")))
        parts: list[str] = []
        if reader.metadata and getattr(reader.metadata, "title", None):
            parts.append(str(reader.metadata.title))
        for page in reader.pages[:25]:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
        return "\n".join(parts)

    def _title_from_section(self, section: str, fallback: str) -> str:
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        for line in lines[:6]:
            candidate = line.strip(" -*:•")
            lowered = normalize_text(candidate)
            words = len(candidate.split())
            if 2 <= words <= 12 and 8 <= len(candidate) <= 120 and not lowered.startswith("close date") and not candidate.endswith("."):
                return candidate
        for line in lines[:6]:
            candidate = line.strip(" -*:•")
            lowered = normalize_text(candidate)
            if 2 <= len(candidate.split()) <= 12 and 8 <= len(candidate) <= 120 and not lowered.startswith("close date"):
                return candidate
        return fallback

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            text = self._extract_text(raw)
        except Exception:
            text = raw.content
        normalized = _clean_text(text)
        if not normalized:
            return []
        sections = _split_sections(text)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for section in sections or [text]:
            section_clean = _clean_text(section)
            if not section_clean:
                continue
            lowered = normalize_text(section_clean)
            if not any(keyword in lowered for keyword in ("grant", "funding", "funded", "award", "research", "science", "innovation", "convocatoria", "beca", "call")):
                continue
            title = self._title_from_section(section, normalized[:140])
            if title in seen:
                continue
            seen.add(title)
            categories = ["pdf"]
            if any(keyword in lowered for keyword in ["grant", "funding", "funded", "award"]):
                categories.append("grants")
            if any(keyword in lowered for keyword in ["research", "science", "investigacion"]):
                categories.append("research")
            if any(keyword in lowered for keyword in ["innovation", "innovacion", "startup"]):
                categories.append("innovation")
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self.source_key.replace("-", " ").title(),
                    country=_extract_country(f"{text}\n{section_clean}"),
                    official_url=raw.url,
                    summary=section_clean[:900],
                    categories=list(dict.fromkeys(categories)),
                    topics=[category for category in categories if category != "pdf"],
                    raw_text=section_clean[:6000],
                    confidence_score=0.68 if len(section_clean) > 160 else 0.5,
                    close_date=_extract_date(f"{text}\n{section_clean}"),
                    funding_amount_raw=_extract_amount(section_clean),
                )
            )
        if candidates:
            return candidates[:12]
        return [
            OpportunityCandidate(
                title=normalized[:180],
                entity=self.source_key.replace("-", " ").title(),
                country=_extract_country(normalized),
                official_url=raw.url,
                summary=normalized[:900],
                categories=["pdf"],
                topics=[],
                raw_text=normalized[:6000],
                confidence_score=0.45,
                close_date=_extract_date(normalized),
                funding_amount_raw=_extract_amount(normalized),
            )
        ]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        return ValidationResult(ok=True)
