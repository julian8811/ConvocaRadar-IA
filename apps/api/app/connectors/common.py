from __future__ import annotations

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
    if not _pw_budget_acquired:
        raise RuntimeError(
            f"Playwright budget exhausted for {url} — "
            f"max {_budget._max_concurrent_for('playwright')} concurrent Playwright sessions"
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


def parse_date_text(text: str | None) -> datetime | None:
    value = clean_text(text)
    if not value:
        return None
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", value)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    slash_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", value)
    if slash_match:
        for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(slash_match.group(1), fmt)
            except ValueError:
                continue
    month_match = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})\b", value)
    if month_match:
        candidate = f"{month_match.group(1).title()} {month_match.group(2)}, {month_match.group(3)}"
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    spanish_month_match = re.search(r"\b([A-Za-záéíóúñ]+)\s+(\d{1,2}),\s+(\d{4})\b", value, flags=re.IGNORECASE)
    if spanish_month_match:
        months = {
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "abril": 4,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "agosto": 8,
            "septiembre": 9,
            "setiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12,
        }
        month = months.get(spanish_month_match.group(1).lower())
        if month:
            try:
                return datetime(int(spanish_month_match.group(3)), month, int(spanish_month_match.group(2)))
            except ValueError:
                pass
    spanish_match = re.search(r"\b(\d{1,2})\s+de\s+([A-Za-záéíóúñ]+)\s+de\s+(\d{4})\b", value, flags=re.IGNORECASE)
    if spanish_match:
        months = {
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "abril": 4,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "agosto": 8,
            "septiembre": 9,
            "setiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12,
        }
        month = months.get(spanish_match.group(2).lower())
        if month:
            try:
                return datetime(int(spanish_match.group(3)), month, int(spanish_match.group(1)))
            except ValueError:
                pass
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
        r"(\$[\d.,]+\s*(?:COP|USD|EUR)?)",
        r"(USD\s*[\d.,]+)",
        r"(EUR\s*[\d.,]+)",
        r"(COP\s*[\d.,]+)",
        r"(€\s*[\d.,]+)",
    ]
    for pattern in tier2:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

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
    request_timeout = timeout_seconds or settings.scraping_timeout_seconds

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
                    timeout=request_timeout,
                    headers=request_headers,
                    follow_redirects=True,
                )
                if _is_private_host(urlparse(str(response.url)).hostname or ""):
                    raise ValueError(f"Blocked redirect to unsafe URL: {response.url}")
                response.raise_for_status()
                content_type = response.headers.get("content-type", fallback_content_type)
                return str(response.url), response.text, content_type
            except Exception as exc:  # pragma: no cover - network fallback path
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
