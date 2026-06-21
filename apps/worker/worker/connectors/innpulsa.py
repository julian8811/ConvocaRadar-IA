import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser, Node

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, launch_chromium, parse_date_text


INNPULSA_API_URL = "https://convocatorias.innpulsacolombia.com/api/convocatorias?active_only=true&include_private=false&include_archive=false"
INNPULSA_SITE_URL = "https://www.innpulsacolombia.com/convocatorias.html"
INNPULSA_DETAIL_BASE = "https://convocatorias.innpulsacolombia.com/convocatoria/"
INNPULSA_CLOSED_KEYWORDS = ("cerrada", "cerrado", "closed", "archivada", "archived", "finalizada", "finalized")


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_money(text: str) -> str | None:
    patterns = [
        r"\$\s?[\d\.\,]+(?:\s?(?:COP|USD|EUR))?",
        r"USD\s?[\d\.\,]+",
        r"COP\s?[\d\.\,]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean(match.group(0))
    return None


def _is_closed_text(text: str) -> bool:
    lowered = _clean(text).lower()
    return any(keyword in lowered for keyword in INNPULSA_CLOSED_KEYWORDS)


def _is_past(date_value: datetime | None) -> bool:
    return bool(date_value and date_value.date() < datetime.now(UTC).date())


class InnpulsaConnector:
    source_key = "innpulsa"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or INNPULSA_SITE_URL

    def _detail_url(self, item_id: str | None, slug: str | None) -> str:
        token = _clean(slug) or _clean(item_id)
        return f"{INNPULSA_DETAIL_BASE}{token}" if token else self.base_url

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            item = _clean(value)
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _candidate_from_api_item(self, item: dict[str, object]) -> OpportunityCandidate | None:
        title = _clean(str(item.get("title") or ""))
        if not title:
            return None
        description = _clean(str(item.get("description") or ""))
        status = _clean(str(item.get("status") or ""))
        category = _clean(str(item.get("category") or ""))
        registration_url = _clean(str(item.get("registration_url") or ""))
        terms_url = _clean(str(item.get("terms_url") or ""))
        item_id = _clean(str(item.get("id") or ""))
        slug = _clean(str(item.get("slug") or ""))
        official_url = self._detail_url(item_id, slug)
        target_audience = _clean(str(item.get("target_audience") or ""))
        purpose = _clean(str(item.get("purpose") or ""))
        benefits = _clean(str(item.get("benefits") or ""))
        terms = self._unique([str(value) for value in item.get("terms") or [] if isinstance(value, str)])
        terms_files = self._unique(
            [
                str(file.get("url") or file.get("name") or "")
                for file in item.get("terms_files") or []
                if isinstance(file, dict)
            ]
        )
        raw_parts = [
            title,
            description,
            f"Estado: {status}" if status else "",
            f"Categoria: {category}" if category else "",
            f"Inicio: {item.get('start_date') or ''}" if item.get("start_date") else "",
            f"Cierre: {item.get('end_date') or ''}" if item.get("end_date") else "",
            f"Registro: {registration_url}" if registration_url else "",
            f"Terminos: {terms_url}" if terms_url else "",
            target_audience,
            purpose,
            benefits,
            " ".join(terms),
            " ".join(terms_files),
        ]
        raw_text = "\n".join(part for part in raw_parts if part).strip()
        categories = self._unique(
            [
                "convocatorias",
                "innovacion",
                "emprendimiento",
                "innpulsa",
                category.lower() if category else "",
            ]
        )
        topics = self._unique(["iNNpulsa", category, status])
        requirements = self._unique([target_audience, purpose]) or ["Revisar la convocatoria oficial"]
        status_lower = status.lower()
        if (
            status_lower in {"closed", "cerrada", "cerrado", "archived", "finalizada", "finished"}
            or _is_closed_text(f"{title} {description} {status} {category} {purpose} {benefits}")
            or _is_past(parse_date_text(str(item.get("end_date") or "")))
        ):
            return None
        return OpportunityCandidate(
            title=title[:180],
            entity="iNNpulsa Colombia",
            country="Colombia",
            official_url=official_url,
            summary=(description or raw_text or title)[:800],
            categories=categories[:5],
            topics=topics[:5],
            requirements=requirements[:5],
            raw_text=raw_text[:6000],
            confidence_score=0.98,
            open_date=parse_date_text(str(item.get("start_date") or "")),
            close_date=parse_date_text(str(item.get("end_date") or "")),
            language="es",
        )

    async def fetch(self) -> RawSourceResult:
        try:
            final_url, content, content_type = await fetch_httpx_text(
                INNPULSA_API_URL,
                headers={"Accept": "application/json"},
                fallback_content_type="application/json",
            )
            metadata: dict[str, object] = {"fetch_mode": "api"}
            try:
                metadata["items"] = json.loads(content)
            except json.JSONDecodeError:
                metadata["items"] = []
            return RawSourceResult(
                source_key=self.source_key,
                url=final_url,
                content=content,
                content_type=content_type,
                metadata=metadata,
            )
        except Exception:
            final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
            cards: list[dict[str, str]] = []
            async with async_playwright() as playwright:
                browser = await launch_chromium(playwright)
                try:
                    from worker.config import get_settings

                    settings = get_settings()
                    page = await browser.new_page(user_agent=settings.scraping_user_agent)
                    await page.goto(self.base_url, wait_until="domcontentloaded", timeout=settings.scraping_timeout_seconds * 1000)
                    await page.wait_for_timeout(4000)
                    cards_locator = page.locator("main article, main section, article, section, .card, [data-testid]")
                    card_count = await cards_locator.count()
                    for index in range(min(card_count, 30)):
                        card = cards_locator.nth(index)
                        title = ""
                        summary = ""
                        detail_url = ""
                        try:
                            title = _clean(await card.locator("h1, h2, h3, h4, a").first.inner_text())
                        except Exception:
                            title = ""
                        try:
                            summary = _clean(await card.locator("p").first.inner_text())
                        except Exception:
                            summary = ""
                        try:
                            href = _clean(await card.locator("a[href]").first.get_attribute("href"))
                            detail_url = urljoin(page.url, href) if href else ""
                        except Exception:
                            detail_url = ""
                        cards.append(
                            {
                                "title": title,
                                "summary": summary,
                                "detail_url": detail_url,
                                "card_text": _clean(await card.inner_text()),
                            }
                        )
                    content = await page.content()
                    content_type = "text/html"
                    final_url = page.url
                finally:
                    await browser.close()
            return RawSourceResult(
                source_key=self.source_key,
                url=final_url,
                content=content,
                content_type=content_type,
                metadata={"fetch_mode": "html", "cards": cards},
            )

    def _candidate_from_container(self, container: Node, raw_url: str) -> OpportunityCandidate | None:
        link_node = None
        for link in container.css("a"):
            href = link.attributes.get("href") or ""
            text = _clean(link.text())
            lowered = text.lower()
            if text and (
                "innpulsacolombia.com" in href
                or href.startswith("/")
                or lowered in {"conoce mas", "conoce mas >", "conoce mas>>", "ver detalles", "postulate", "postulate ahora"}
                or "conoce mas" in lowered
                or "postulate" in lowered
            ):
                link_node = link
                if lowered not in {"conoce mas", "ver detalles", "postulate", "postulate ahora"}:
                    break
        if not link_node:
            return None

        title = clean_text(link_node.text())
        href = link_node.attributes.get("href") or ""
        text = _clean(container.text())
        summary = text.replace(title, "", 1).strip(" -")
        date = parse_date_text(text)
        money = _extract_money(text)
        if _is_closed_text(text) or _is_past(date):
            return None
        if title.lower() in {"conoce mas", "ver detalles", "postulate", "postulate ahora"}:
            for separator in ("Conoce mas", "Ver detalles", "Postulate", "Postulate ahora"):
                if separator in text:
                    title = _clean(text.split(separator)[0])
                    break
        if len(title) < 8:
            return None
        return OpportunityCandidate(
            title=title[:180],
            entity="iNNpulsa Colombia",
            country="Colombia",
            official_url=urljoin(raw_url, href),
            summary=summary[:600] or title,
            categories=["innovacion", "emprendimiento", "innpulsa"],
            topics=["iNNpulsa", "emprendimiento"],
            raw_text=text,
            confidence_score=0.74,
            open_date=date,
            funding_amount_raw=money,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if raw.content_type.startswith("application/json") or raw.metadata.get("fetch_mode") == "api":
            try:
                payload = json.loads(raw.content)
            except json.JSONDecodeError:
                payload = []
            items = payload if isinstance(payload, list) else []
            if isinstance(payload, dict):
                items = payload.get("data") or payload.get("items") or payload.get("results") or []
            if isinstance(items, dict):
                items = items.get("items") or items.get("results") or []
            candidates: list[OpportunityCandidate] = []
            seen: set[str] = set()
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                candidate = self._candidate_from_api_item(item)
                if not candidate or candidate.official_url in seen:
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)
            if candidates:
                return candidates[:60]

        browser_cards = raw.metadata.get("cards") or []
        if browser_cards:
            candidates: list[OpportunityCandidate] = []
            seen: set[str] = set()
            for card in browser_cards:
                title = _clean(card.get("title"))
                detail_url = _clean(card.get("detail_url"))
                summary = _clean(card.get("summary"))
                card_text = _clean(card.get("card_text"))
                if not title or not detail_url or detail_url in seen:
                    continue
                seen.add(detail_url)
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="iNNpulsa Colombia",
                        country="Colombia",
                        official_url=detail_url,
                        summary=summary[:700] or title,
                        categories=["innovacion", "emprendimiento", "innpulsa"],
                        topics=["iNNpulsa", "emprendimiento"],
                        raw_text=card_text[:3000],
                        confidence_score=0.88,
                    )
                )
            if candidates:
                return candidates[:50]

        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        containers = [
            *tree.css("article"),
            *tree.css("section"),
            *tree.css(".card"),
            *tree.css(".views-row"),
            *tree.css(".swiper-slide"),
            *tree.css(".portfolio-item"),
            *tree.css("li"),
        ]
        for container in containers:
            candidate = self._candidate_from_container(container, raw.url)
            if not candidate or candidate.official_url in seen:
                continue
            if "innpulsacolombia.com" not in candidate.official_url and "convocatorias.innpulsacolombia.com" not in candidate.official_url:
                continue
            seen.add(candidate.official_url)
            candidates.append(candidate)
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "innpulsacolombia.com" not in candidate.official_url and "convocatorias.innpulsacolombia.com" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside iNNpulsa")
        if _is_closed_text(f"{candidate.title} {candidate.summary} {candidate.raw_text}") or _is_past(candidate.close_date):
            return ValidationResult(ok=False, reason="Opportunity appears closed")
        return ValidationResult(ok=True)
