from __future__ import annotations

import asyncio
import html
import re
import socket
from datetime import datetime
import unicodedata
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings
from app.core.http_client import http_client

# Lazily-imported domain budget singleton — resolved at call time to
# avoid circular imports during app bootstrap.
_DOMAIN_BUDGET: object | None = None


def _get_budget():
    """Return the module-level DomainBudgetManager singleton."""
    global _DOMAIN_BUDGET
    if _DOMAIN_BUDGET is None:
        from app.scraper.domain_budget import DomainBudgetManager

        _DOMAIN_BUDGET = DomainBudgetManager()
    return _DOMAIN_BUDGET

CHROMIUM_CONTAINER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
PLAYWRIGHT_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


async def launch_chromium(playwright, *, headless: bool = True):
    return await playwright.chromium.launch(headless=headless, args=CHROMIUM_CONTAINER_ARGS)


async def render_page_html(
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout_ms: int | None = None,
    wait_selector: str | None = None,
    wait_selector_timeout_ms: int = 8000,
    post_wait_ms: int = 500,
    user_agent: str | None = None,
) -> tuple[str, str, str]:
    from urllib.parse import urlparse

    settings = get_settings()
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    request_user_agent = user_agent or settings.scraping_user_agent
    navigation_timeout_ms = timeout_ms or settings.scraping_timeout_seconds * 1000

    # Per-domain budget for Playwright — max 1 concurrent Playwright session
    _budget = _get_budget()
    _pw_budget_acquired = _budget.acquire("playwright")
    budget_wait_deadline = asyncio.get_running_loop().time() + min(
        30.0, max(5.0, float(settings.scraping_timeout_seconds))
    )
    while not _pw_budget_acquired and asyncio.get_running_loop().time() < budget_wait_deadline:
        await asyncio.sleep(0.1)
        _pw_budget_acquired = _budget.acquire("playwright")
    if not _pw_budget_acquired:
        raise RuntimeError(
            f"Timed out waiting for a Playwright slot for {url} — "
            f"max {_budget._max_concurrent_for('playwright')} concurrent sessions"
        )

    from playwright.async_api import async_playwright

    try:
        for attempt in range(2):
            try:
                async with async_playwright() as playwright:
                    browser = await launch_chromium(playwright)
                    try:
                        page = await browser.new_page(user_agent=request_user_agent)

                        async def _route_handler(route) -> None:
                            if route.request.resource_type in PLAYWRIGHT_BLOCKED_RESOURCE_TYPES:
                                await route.abort()
                                return
                            await route.continue_()

                        await page.route("**/*", _route_handler)
                        await page.goto(url, wait_until=wait_until, timeout=navigation_timeout_ms)
                        if wait_selector:
                            try:
                                await page.wait_for_selector(wait_selector, timeout=wait_selector_timeout_ms)
                            except Exception:
                                pass
                        if post_wait_ms > 0:
                            await page.wait_for_timeout(post_wait_ms)
                        final_url = page.url
                        if _is_private_host(urlparse(final_url).hostname or ""):
                            raise ValueError(f"Blocked redirect to unsafe URL: {final_url}")
                        return final_url, await page.content(), "text/html"
                    finally:
                        await browser.close()
            except Exception as exc:
                if attempt == 0 and "Executable doesn't exist" in str(exc):
                    import subprocess, sys as _sys
                    _sys.stdout.flush()
                    subprocess.run(
                        [_sys.executable, "-m", "playwright", "install", "chromium", "chromium-headless-shell"],
                        capture_output=True, timeout=180,
                    )
                    continue
                raise RuntimeError(
                    f"Playwright/Chromium not available: {exc}. "
                    "Install with: playwright install chromium"
                ) from exc
    finally:
        if _pw_budget_acquired:
            _budget.release("playwright")


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?:[.#]?[A-Za-z][\w-]*\s*\{[^{}]*\}\s*)+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", html.unescape(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def looks_like_noise_text(value: str | None) -> bool:
    text = clean_text(value).lower()
    if not text:
        return False
    if "{" in text or "}" in text:
        return True
    return bool(
        re.search(
            r"(<style[\s\S]*?</style>|<script[\s\S]*?</script>|color:\s*white|background-color:|\.box-address|\.caja|display:\s*flex|justify-content:\s*center|font-weight:\s*bold|text-decoration:\s*underline|font-size:|padding:|margin:|border:|budgetyearscolumns|plannedopeningdate|deadlinedate|action:|action\"?:|action'?:)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_private_host(hostname: str) -> bool:
    host = hostname.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".lan") or host.endswith(".corp"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    try:
        addrs = socket.getaddrinfo(host, 80)
        for family, _type, _proto, _cname, sockaddr in addrs:
            raw = sockaddr[0]
            try:
                addr = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
                return True
    except OSError:
        pass
    return False


def is_allowed_host(url: str, allowed_domains: list[str] | tuple[str, ...] | None = None) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if _is_private_host(host):
        return False
    if not allowed_domains:
        return True
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def safe_urljoin(base_url: str, href: str | None) -> str:
    return urljoin(base_url, href or "")


def extract_close_date(text: str) -> datetime | None:
    """Extract a deadline/close date from text using Spanish & English patterns.
    Tries keyword-prefixed patterns first (more reliable), then falls back to
    any date-looking text near deadline keywords.
    """
    if not text:
        return None
    _text = text[:3000]  # limit to first 3000 chars for performance

    # ── Tier 1: Keyword-prefixed patterns (high precision) ──────────────
    tier1 = [
        # Spanish: "fecha de cierre: 8 de mayo de 2026"
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite|limite|maxima|maxima|tope))\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        # Spanish: "fecha de cierre de la convocatoria: 15/06/2026"
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite)\s+(?:de\s+la\s+)?(?:convocatoria|presentacion|presentación|solicitud))\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        # Spanish: "cierra el 08 de mayo de 2026"
        r"(?:cierra|vence|finaliza|termina)\s+(?:el\s+)?(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        # English: "deadline: May 8, 2026"
        r"(?:deadline|closing\s+date|submission\s+deadline|application\s+deadline|applications?\s+due|proposals?\s+due)\s*[:\-]?\s*([a-z]+\s+\d{1,2},?\s+\d{4})",
        # Spanish/English: "hasta el 8 de mayo de 2026"
        r"(?:hasta\s+(?:el\s+)?(?:dia\s+)?)(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        # Spanish: "postulación hasta: 8/5/2026"
        r"(?:postulacion|postulación|aplicacion|aplicación|envio|envío|recepcion|recepción|inscripcion|inscripción)\s+(?:hasta|cierra|finaliza)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        # Spanish: "convocatoria cierre: 15/06/2026" / "convocatoria cierra: 15/06/2026"
        r"(?:convocatoria\s+)(?:cierre|cierra|finaliza|vence)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        # "plazo: 8 de mayo de 2026" / "plazo máximo: ..."
        r"(?:plazo\s+(?:maximo|máximo|tope|max|)?)\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        # "presentación de ofertas hasta: 15/06/2026"
        r"(?:presentacion|presentación)\s+(?:de\s+)?(?:ofertas|solicitudes|propuestas)\s+(?:hasta|cierra|finaliza)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        # "apertura: ... cierre: ..." pattern (common in Latin American portals)
        r"(?:cierre|fecha\s+de\s+cierre)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    ]
    for pattern in tier1:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date_text(match.group(1))
            if parsed:
                return parsed

    # ── Tier 2: Any date after a deadline keyword (broader match) ───────
    tier2 = [
        # English: "closes May 8, 2026" / "due May 8, 2026" / "by May 8, 2026"
        r"(?:closes|due date|due on|by\s+)\s*([a-z]+\s+\d{1,2},?\s+\d{4})",
        # "before May 8, 2026" / "until May 8, 2026"
        r"(?:before|until|antes\s+del|a\s+mas\s+tardar)\s+(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})",
        # Bare Spanish date after "el" ("recibimos hasta el 8 de mayo de 2026")
        r"(?:hasta|antes\s+del)\s+(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        # Bare numeric date preceded by keyword
        r"(?:cierre|deadline|closing|due)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    ]
    for pattern in tier2:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date_text(match.group(1))
            if parsed:
                return parsed

    # ── Tier 3: Last resort — any ISO or slash date near keywords ───────
    for pattern in [
        r"(?:cierra|deadline|cierre|vence|closing|due)\s*(?:\:)?\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date_text(match.group(1))
            if parsed:
                return parsed

    return None


def _parse_spanish_month(text: str, month_group: int, day_group: int, year_group: int, match) -> datetime | None:
    """Try to parse a Spanish date using the module-level month map."""
    month = _SPANISH_MONTHS.get(match.group(month_group).lower())
    if month is None:
        return None
    try:
        return datetime(int(match.group(year_group)), month, int(match.group(day_group)))
    except ValueError:
        return None


def parse_date_text(text: str | None) -> datetime | None:
    value = clean_text(text)
    if not value:
        return None
    # 1. ISO format: 2027-06-30
    iso_match = _ISO_DATE.search(value)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    # 2. Slash format: 06/30/2027 or 30/06/2027
    slash_match = _SLASH_DATE.search(value)
    if slash_match:
        for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(slash_match.group(1), fmt)
            except ValueError:
                continue
    # 3. English: "June 30, 2027" or "Jun 30, 2027"
    eng_match = _ENGLISH_DATE.search(value)
    if eng_match:
        candidate = f"{eng_match.group(1).title()} {eng_match.group(2)}, {eng_match.group(3)}"
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    # 4. Spanish comma: "junio 30, 2027"
    es_comma = _SPANISH_DATE_COMMA.search(value)
    if es_comma:
        result = _parse_spanish_month(text, 1, 2, 3, es_comma)
        if result:
            return result
    # 5. Spanish "de": "30 de junio de 2027"
    es_de = _SPANISH_DATE_DE.search(value)
    if es_de:
        result = _parse_spanish_month(text, 2, 1, 3, es_de)
        if result:
            return result
    return None


def extract_funding_amount(text: str) -> str | None:
    """Extract a funding amount from text using Spanish & English patterns.

    Tries keyword-prefixed patterns first (higher precision), then falls
    back to any amount-looking text. Returns the raw amount string or None.
    """
    if not text:
        return None
    _text = text[:3000]

    # ── Tier 1: Keyword-prefixed patterns ──────────────────────────────
    tier1 = [
        # Spanish: "financiamiento: USD 500.000"
        r"(?:financiamiento|presupuesto|monto|valor|recursos|fondos|aporte|subvencion|subvención|inversion|inversión|total|cuantía)\s*(?:maximo|máximo|total|estimado|disponible|asignado|solicitado)?\s*[:\-]?\s*([\w\s.$€£,]+?\d[\d.,\s]*(?:million|millón|millones|m|k|usd|cop|eur)?)",
        # English: "budget: USD 500,000"
        r"(?:budget|funding|grant\s+amount|award\s+amount|total\s+funding|project\s+budget|max\s+funding)\s*[:\-]?\s*([\w\s.$€£,]+?\d[\d.,\s]*(?:million|m|k|usd|cop|eur)?)",
        # Spanish: "hasta USD 500.000"
        r"(?:hasta|de\s+hasta|por\s+hasta)\s*([\w\s.$€£]*\d[\d.,]+\s*(?:USD|EUR|COP|usd|eur|cop)?)",
        # English: "up to USD 500,000"
        r"(?:up\s+to|of\s+up\s+to)\s*([\w\s.$€£]*\d[\d.,]+\s*(?:USD|EUR|COP|usd|eur|cop)?)",
    ]
    for pattern in tier1:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            result = match.group(1).strip()
            if result:
                return result

    # ── Tier 2: Any currency amount with known prefix/suffix ───────────
    tier2 = [
        r"(USD\s*[\d.,]{3,})",
        r"(EUR\s*[\d.,]{3,})",
        r"(COP\s*[\d.,]{3,})",
        r"(BRL\s*[\d.,]{3,})",
        r"(GBP\s*[\d.,]{3,})",
        r"(€\s*[\d.,]{3,})",
        r"(£\s*[\d.,]{3,})",
        r"(R\$\s*[\d.,]{3,})",
        r"\$(\d[\d.,]{2,}\s*(?:COP|USD|EUR)?)",
    ]
    for pattern in tier2:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            result = match.group(1).strip()
            # Reject single/double-digit values (likely page numbers, counts)
            digits_only = re.sub(r"[^\d]", "", result)
            if digits_only and int(digits_only) < 500 and not re.search(r"(?:USD|EUR|COP|BRL|GBP)", result, re.IGNORECASE):
                continue
            return result

    return None


def unique_links(links: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        normalized = clean_text(link)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


FETCH_TIMEOUT_CAP = 120  # Hard cap per request (seconds), even if config says higher

# ── Date parsing constants ────────────────────────────────────────────────
_SPANISH_MONTHS: dict[str, int] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_ENGLISH_DATE = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})\b")
_SPANISH_DATE_COMMA = re.compile(r"\b([A-Za-záéíóúñ]+)\s+(\d{1,2}),\s+(\d{4})\b", flags=re.IGNORECASE)
_SPANISH_DATE_DE = re.compile(r"\b(\d{1,2})\s+de\s+([A-Za-záéíóúñ]+)\s+de\s+(\d{4})\b", flags=re.IGNORECASE)

# Content-Type patterns that indicate JSON responses, even when the
# server sends a different Content-Type header. Some API endpoints
# send text/html or text/plain with JSON body.
_JSON_CONTENT_PATTERNS = (
    "application/json",
    "application/ld+json",
    "application/vnd.api+json",
    "text/json",
)


def _looks_like_json(content: str) -> bool:
    """Quick check if content looks like JSON without full parsing."""
    stripped = content.lstrip()
    return bool(stripped and stripped[0] in "[{")


async def fetch_httpx_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    retries: int = 2,
    fallback_content_type: str = "text/html",
    playwright_fallback: bool = True,
    timeout_seconds: int | None = None,
) -> tuple[str, str, str]:
    from urllib.parse import urlparse

    settings = get_settings()
    request_headers = {"User-Agent": settings.scraping_user_agent}
    if headers:
        request_headers.update(headers)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    request_timeout = min(timeout_seconds or settings.scraping_timeout_seconds, FETCH_TIMEOUT_CAP)

    # Per-domain budget check
    _budget = _get_budget()
    _delay = _budget.delay_for(url)
    if _delay > 0:
        import asyncio as _asyncio

        await _asyncio.sleep(_delay)
    _budget_acquired = _budget.acquire(url)
    if not _budget_acquired:
        raise RuntimeError(f"Domain budget exhausted for {url}")

    try:
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(max(retries, 1)):
            try:
                client = await http_client()
                response = await client.request(
                    method,
                    url,
                    json=payload,
                    timeout=request_timeout,
                    headers=request_headers,
                    follow_redirects=True,
                )
                if _is_private_host(urlparse(str(response.url)).hostname or ""):
                    raise ValueError(f"Blocked redirect to unsafe URL: {response.url}")
                last_status = response.status_code
                response.raise_for_status()
                # Content-Type detection: use header but detect JSON body
                raw_ct = (response.headers.get("content-type") or fallback_content_type).lower()
                body_text = response.text
                if not any(p in raw_ct for p in _JSON_CONTENT_PATTERNS) and _looks_like_json(body_text):
                    raw_ct = "application/json"
                return str(response.url), body_text, raw_ct
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt + 1 >= retries:
                    raise RuntimeError(
                        f"Timeout fetching {url} after {request_timeout}s (attempt {attempt + 1}/{retries})"
                    ) from exc
            except httpx.HTTPStatusError as exc:
                last_error = exc
                last_status = exc.response.status_code
                if attempt + 1 >= retries:
                    # Don't raise — fall through to Playwright fallback (if enabled).
                    # WAF/Cloudflare blocks (403) are indistinguishable from
                    # real 403s at the HTTP layer; Playwright with a real browser
                    # can often bypass them.
                    break
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= retries:
                    break
        if not playwright_fallback:
            raise last_error or RuntimeError(f"Failed to fetch {url}")
        if _is_private_host(parsed_url.hostname or ""):
            raise last_error or ValueError(f"Blocked unsafe URL: {url}")
        return await render_page_html(
            url,
            user_agent=request_headers["User-Agent"],
            timeout_ms=request_timeout * 1000,
        )
    finally:
        if _budget_acquired:
            _budget.release(url)


async def fetch_httpx_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    retries: int = 2,
    fallback_content_type: str = "application/octet-stream",
) -> tuple[str, bytes, str]:
    from urllib.parse import urlparse

    settings = get_settings()
    request_headers = {"User-Agent": settings.scraping_user_agent}
    if headers:
        request_headers.update(headers)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")

    # Per-domain budget check
    _budget = _get_budget()
    _delay = _budget.delay_for(url)
    if _delay > 0:
        import asyncio as _asyncio

        await _asyncio.sleep(_delay)
    _budget_acquired = _budget.acquire(url)
    if not _budget_acquired:
        raise RuntimeError(f"Domain budget exhausted for {url}")

    try:
        last_error: Exception | None = None
        for attempt in range(max(retries, 1)):
            try:
                client = await http_client()
                response = await client.request(
                    method,
                    url,
                    json=payload,
                    timeout=settings.scraping_timeout_seconds,
                    headers=request_headers,
                    follow_redirects=True,
                )
                if _is_private_host(urlparse(str(response.url)).hostname or ""):
                    raise ValueError(f"Blocked redirect to unsafe URL: {response.url}")
                response.raise_for_status()
                content_type = response.headers.get("content-type", fallback_content_type)
                return str(response.url), response.content, content_type
            except Exception as exc:  # pragma: no cover - network fallback path
                last_error = exc
                if attempt + 1 >= retries:
                    break
        raise last_error or RuntimeError(f"Failed to fetch {url}")
    finally:
        if _budget_acquired:
            _budget.release(url)


# ── Detail-page enrichment for sitemap-based connectors ────────────────

DETAIL_PAGE_TIMEOUT: int = 15


async def enrich_from_detail_page(url: str) -> dict | None:
    """Fetch a detail page and extract title, close_date, funding_amount."""
    try:
        _, content, _ct = await fetch_httpx_text(
            url, timeout_seconds=DETAIL_PAGE_TIMEOUT, retries=1, playwright_fallback=False,
        )
    except Exception:
        return None

    from selectolax.parser import HTMLParser
    import json as _json

    result: dict = {}
    tree = HTMLParser(content)

    for script in tree.css("script[type='application/ld+json']"):
        try:
            payload = _json.loads(script.text() or "{}")
        except _json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("name") or item.get("title") or "").strip()
            if title:
                result["title"] = title
            desc = str(item.get("description") or item.get("summary") or "").strip()
            if desc:
                result["summary"] = desc
            cd = item.get("closeDate") or item.get("close_date") or item.get("deadline") or item.get("endDate")
            if cd:
                parsed = parse_date_text(str(cd))
                if parsed:
                    result["close_date"] = parsed
            amount = str(item.get("funding", item.get("fundingAmount", ""))).strip()
            if amount:
                result["funding_amount_raw"] = amount
            break

    if "title" not in result:
        og_title = tree.css_first("meta[property='og:title']")
        if og_title:
            value = (og_title.attributes.get("content") or "").strip()
            if value:
                result["title"] = value

    if "summary" not in result:
        og_desc = tree.css_first("meta[property='og:description']")
        if og_desc:
            value = (og_desc.attributes.get("content") or "").strip()
            if value:
                result["summary"] = value
        if "summary" not in result:
            meta_desc = tree.css_first("meta[name='description']")
            if meta_desc:
                value = (meta_desc.attributes.get("content") or "").strip()
                if value:
                    result["summary"] = value

    if "title" not in result:
        h1 = tree.css_first("h1")
        if h1:
            value = clean_text(h1.text())
            if value:
                result["title"] = value

    if "close_date" not in result:
        body = tree.css_first("body")
        if body:
            all_text = clean_text(body.text())
            cd = extract_close_date(all_text)
            if cd:
                result["close_date"] = cd

    if "funding_amount_raw" not in result:
        body = tree.css_first("body")
        if body:
            all_text = clean_text(body.text())
            amount = extract_funding_amount(all_text)
            if amount:
                result["funding_amount_raw"] = amount

    return result if result.get("title") else None


async def enrich_candidates_batch(
    candidates: list[OpportunityCandidate], max_fetches: int = 10,
) -> list[OpportunityCandidate]:
    """Batch-enrich low-confidence candidates by fetching detail pages.

    Fetches up to ``max_fetches`` detail pages concurrently, extracts
    close_date, funding_amount, and title, then returns an enriched
    copy of the full candidate list.
    """
    import asyncio
    from copy import deepcopy

    to_enrich = candidates[:max_fetches]
    tasks = {c.official_url: enrich_from_detail_page(c.official_url) for c in to_enrich}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    url_to_data: dict[str, dict | None] = {}
    for url, task in zip(tasks, results):
        url_to_data[url] = task if isinstance(task, dict) and task.get("title") else None

    enriched: list[OpportunityCandidate] = []
    for c in candidates:
        detail = url_to_data.get(c.official_url)
        if detail:
            enriched.append(
                OpportunityCandidate(
                    title=(detail.get("title") or c.title)[:180],
                    entity=c.entity,
                    country=c.country,
                    official_url=c.official_url,
                    summary=(detail.get("summary") or c.summary)[:700],
                    categories=c.categories,
                    raw_text=c.raw_text,
                    confidence_score=0.82,
                    close_date=detail.get("close_date") or c.close_date,
                    funding_amount_raw=detail.get("funding_amount_raw") or c.funding_amount_raw,
                )
            )
        else:
            enriched.append(deepcopy(c))
    return enriched
