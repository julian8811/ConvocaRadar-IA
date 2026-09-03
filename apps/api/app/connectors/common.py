from __future__ import annotations

import asyncio
import html
import re
import socket
from collections.abc import Sequence
from datetime import datetime
import unicodedata
import ipaddress
from urllib.parse import urljoin, urlparse  # noqa: F401 — kept at module level by test_scraper_fixes guard

import httpx

from app.connectors.base import OpportunityCandidate
from app.core.config import get_settings
from app.core.http_client import http_client

# ── SPA shell detection (023 S3) ──────────────────────────────────────────
SPA_SHELL_THRESHOLD: int = 8000  # bytes/chars below which text/html with no h1 is considered shell
SPA_ALLOWLIST: set[str] = {"grants-gov", "grants.gov", "simpler-grants", "simpler.grants.gov", "simpler"}


def is_shell_response(content: str, content_type: str, candidates: int) -> bool:
    """Detect thin SPA shell that warrants a single PW retry.

    Conditions (all must hold):
    - candidates == 0
    - content_type starts with text/html
    - len(content) < SPA_SHELL_THRESHOLD
    - no <h1 tag in content
    """
    if candidates != 0:
        return False
    ct = (content_type or "").lower().strip()
    if not ct.startswith("text/html"):
        return False
    if len(content or "") >= SPA_SHELL_THRESHOLD:
        return False
    # h1 missing -> shell; if h1 present we have real content
    if re.search(r"<h1\b", content or "", flags=re.IGNORECASE):
        return False
    return True


async def maybe_retry_shell_with_pw(
    *,
    content: str,
    content_type: str,
    candidates: int,
    source_key: str,
    url: str,
) -> tuple[str, str, str] | None:
    """If shell detected and allowlisted and flag on, retry once via Playwright.

    Returns (final_url, new_content, new_content_type) on retry, else None.
    Exactly one PW call; gate: flag + allowlist + is_shell_response.
    """
    try:
        if not get_settings().extraction_spa_retry:
            return None
    except Exception:
        return None
    # allowlist: source_key contains grants/simpler or host matches
    sk = (source_key or "").lower()
    allow = any(token in sk for token in ("grants-gov", "grants.gov", "simpler", "simpler-grants"))
    if not allow:
        # also check url host
        try:
            host = (urlparse(url).hostname or "").lower()
            allow = any(h in host for h in ("grants.gov", "simpler.grants.gov"))
        except Exception:
            pass
    if not allow:
        return None
    if not is_shell_response(content, content_type, candidates):
        return None
    try:
        return await render_page_html(url)
    except Exception:
        return None


# Unified domain budget singleton — delegates to scraper.domain_budget single source.
_DOMAIN_BUDGET: object | None = None  # kept for test shim compatibility


def _get_budget():
    """Return the shared DomainBudgetManager singleton (single source)."""
    from app.scraper.domain_budget import get_domain_budget

    return get_domain_budget()


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
    # Delegates to scraper.playwright_pool.PlaywrightBrowserPool singleton (isolated per connector)
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
                                await page.wait_for_selector(
                                    wait_selector, timeout=wait_selector_timeout_ms
                                )
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
                    import subprocess
                    import sys as _sys

                    _sys.stdout.flush()
                    subprocess.run(
                        [
                            _sys.executable,
                            "-m",
                            "playwright",
                            "install",
                            "chromium",
                            "chromium-headless-shell",
                        ],
                        capture_output=True,
                        timeout=180,
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


_CLOSED_STATUS_RE = re.compile(
    r"""
    \b(
        cerrad[oa]s?
        | closed
        | finalizad[oa]s?
        | vencid[oa]s?
        | archivad[oa]s?
        | expirad[oa]s?
        | expired
        | encerrad[oa]s?
        | fechad[oa]s?
        | findad[oa]s?
        | conclu[íi]d[oa]s?
        | no\s+vigente
        | ya\s+no\s+est[aá]\s+(disponible|abierta|abierto)
        | no\s+longer\s+accepting
        | not\s+accepting\s+applications
        | applications?\s+closed
        | deadline\s+passed
        | call\s+closed
        | closed\s+call
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def looks_closed_text(value: str | None) -> bool:
    """True when *value* states that a call is closed — not a 'cierre' date label."""
    text = clean_text(value)
    if not text:
        return False
    return bool(_CLOSED_STATUS_RE.search(text))


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
    if (
        host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".lan")
        or host.endswith(".corp")
    ):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return (
            ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
        )
    try:
        addrs = socket.getaddrinfo(host, 80)
        for family, _type, _proto, _cname, sockaddr in addrs:
            raw = sockaddr[0]
            try:
                addr = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
            ):
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


def _year_guard(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    try:
        s = get_settings()
        y_min = int(s.extraction_year_min)
        y_max = int(s.extraction_year_max)
    except Exception:
        y_min, y_max = 2024, 2028
    if dt.year < y_min or dt.year > y_max:
        return None
    return dt


def extract_dates(text: str) -> tuple[datetime | None, datetime | None]:
    """Extract (open_date, close_date) from text using tier fallback + dateparser.

    Finds all date candidates via keyword-prefixed tiers and generic sweep,
    parses each with ``parse_date_text`` (dateparser DMY), filters by year
    window 2024-2028, then assigns earliest→open, latest→close. Single
    candidate → (None, that). No candidates → (None, None).
    """
    if not text:
        return None, None
    _text = text[:4000]
    candidates: list[datetime] = []
    seen: set[str] = set()

    # Tier patterns that capture a date string group(1)
    tier_patterns = [
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite|maxima|tope))\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite)\s+(?:de\s+la\s+)?(?:convocatoria|presentacion|presentación|solicitud))\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:data\s+(?:de\s+)?encerramento|prazo\s+(?:maximo|máximo|final|)?|data\s+limite|data\s+final)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:inscrições?|inscricao|inscrição)\s+(?:ate|até|encerram|finalizam)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:cierra|vence|finaliza|termina)\s+(?:el\s+)?(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:deadline|closing\s+date|submission\s+deadline|application\s+deadline|applications?\s+due|proposals?\s+due)\s*[:\-]?\s*([a-z]+\s+\d{1,2},?\s+\d{4})",
        r"(?:hasta\s+(?:el\s+)?(?:dia\s+)?)(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:postulacion|postulación|aplicacion|aplicación|envio|envío|recepcion|recepción|inscripcion|inscripción)\s+(?:hasta|cierra|finaliza)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:convocatoria\s+)(?:cierre|cierra|finaliza|vence)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:plazo\s+(?:maximo|máximo|tope|max|)?)\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(?:presentacion|presentación)\s+(?:de\s+)?(?:ofertas|solicitudes|propuestas)\s+(?:hasta|cierra|finaliza)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:cierre|fecha\s+de\s+cierre)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:apertura|inicio|abre|abierta)\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:desde|del)\s+(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(\d{1,2}\s+(?:de\s+)?[a-záéíóúñ]+,?\s+(?:de\s+)?\d{4})",
        r"(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
        r"(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+\d{4})",
        r"(\d{1,2}\s+[a-záéíóúñ]+\s+\d{4})",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"([a-z]+\s+\d{1,2},?\s+\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]
    for pat in tier_patterns:
        for m in re.finditer(pat, _text, flags=re.IGNORECASE):
            raw = m.group(1).strip()
            if raw.lower() in seen:
                continue
            seen.add(raw.lower())
            parsed = parse_date_text(raw)
            parsed = _year_guard(parsed)
            if parsed and parsed not in candidates:
                candidates.append(parsed)

    # Generic desde...hasta explicit pair fallback (permissive month form)
    hasta_match = re.search(
        r"desde\s+(\d{1,2}\s+(?:de\s+)?[a-záéíóúñ]+\s+(?:de\s+)?\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\s+(?:hasta|al)\s+(\d{1,2}\s+(?:de\s+)?[a-záéíóúñ]+\s+(?:de\s+)?\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        _text,
        flags=re.IGNORECASE,
    )
    if hasta_match:
        for idx in (1, 2):
            raw = hasta_match.group(idx).strip()
            p = _year_guard(parse_date_text(raw))
            if p and p not in candidates:
                candidates.append(p)

    if not candidates:
        return None, None
    candidates.sort()
    if len(candidates) == 1:
        return None, candidates[0]
    return candidates[0], candidates[-1]


def extract_close_date(text: str) -> datetime | None:
    """Wrapper over extract_dates — returns close_date (latest)."""
    if not text:
        return None
    # Fast tier-1 path preserved for backward compat precision, then fallback to tuple
    _text = text[:3000]
    labeled = re.search(
        rf"(?:cierre|fecha\s+de\s+cierre|deadline|closing\s+date|submission\s+deadline)\s*[:\-]?\s*({_DATE_VALUE_ALT})",
        _text,
        flags=re.IGNORECASE,
    )
    if labeled:
        parsed = _year_guard(parse_date_text(labeled.group(1)))
        if parsed:
            return parsed
    tier1 = [
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite|maxima|tope))\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite)\s+(?:de\s+la\s+)?(?:convocatoria|presentacion|presentación|solicitud))\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:data\s+(?:de\s+)?encerramento|prazo\s+(?:maximo|máximo|final|)?|data\s+limite|data\s+final)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:inscrições?|inscricao|inscrição)\s+(?:ate|até|encerram|finalizam)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:cierra|vence|finaliza|termina)\s+(?:el\s+)?(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:deadline|closing\s+date|submission\s+deadline|application\s+deadline|applications?\s+due|proposals?\s+due)\s*[:\-]?\s*([a-z]+\s+\d{1,2},?\s+\d{4})",
        r"(?:hasta\s+(?:el\s+)?(?:dia\s+)?)(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:postulacion|postulación|aplicacion|aplicación|envio|envío|recepcion|recepción|inscripcion|inscripción)\s+(?:hasta|cierra|finaliza)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:convocatoria\s+)(?:cierre|cierra|finaliza|vence)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:plazo\s+(?:maximo|máximo|tope|max|)?)\s*[:\-]?\s*(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(?:presentacion|presentación)\s+(?:de\s+)?(?:ofertas|solicitudes|propuestas)\s+(?:hasta|cierra|finaliza)\s*(?:\:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(?:cierre|fecha\s+de\s+cierre)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    ]
    for pattern in tier1:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            parsed = _year_guard(parse_date_text(match.group(1)))
            if parsed:
                return parsed
    # fallback to tuple
    _, close = extract_dates(text)
    return close


def extract_open_date(text: str) -> datetime | None:
    """Extract the opening/publication date of a call.

    Mirrors :func:`extract_close_date`: tier-1 labelled Spanish/English/
    Portuguese opening patterns first (higher precision), then falls back to
    the earliest candidate found by :func:`extract_dates`.
    """
    if not text:
        return None
    _text = text[:3000]
    for pattern in _OPEN_DATE_PATTERNS:
        match = pattern.search(_text)
        if match:
            parsed = _year_guard(parse_date_text(match.group(1)))
            if parsed:
                return parsed
    open_date, _ = extract_dates(text)
    return open_date


def _parse_spanish_month(
    text: str, month_group: int, day_group: int, year_group: int, match
) -> datetime | None:
    """Try to parse a Spanish date using the module-level month map."""
    month = _SPANISH_MONTHS.get(match.group(month_group).lower())
    if month is None:
        return None
    try:
        return datetime(int(match.group(year_group)), month, int(match.group(day_group)))
    except ValueError:
        return None


_DATEPARSER_STATE: dict[str, object] = {}


def _load_dateparser():
    """Return the dateparser module, or None if it is not installed.

    dateparser is a declared dependency and the primary parser for the
    Spanish/Portuguese date forms these sources use; the regex tiers below are
    only a reduced fallback. A missing install used to be swallowed silently,
    which degraded every date in the pipeline with no signal, so warn once.
    """
    if "module" not in _DATEPARSER_STATE:
        try:
            import dateparser as _dp

            _DATEPARSER_STATE["module"] = _dp
        except ImportError:
            import logging

            logging.getLogger(__name__).warning(
                "dateparser is not installed; date extraction is running on the "
                "reduced regex fallback only. Install it to restore full coverage."
            )
            _DATEPARSER_STATE["module"] = None
    return _DATEPARSER_STATE["module"]


def parse_date_text(text: str | None) -> datetime | None:
    value = clean_text(text)
    if not value:
        return None
    # Unambiguous ISO (YYYY-MM-DD) first: dateparser with DATE_ORDER=DMY
    # otherwise reads "2026-04-01" as 4 January.
    iso_match = _ISO_DATE.search(value)
    if iso_match and iso_match.start() <= 1:
        try:
            parsed = _year_guard(datetime.strptime(iso_match.group(1), "%Y-%m-%d"))
            if parsed:
                return parsed
        except ValueError:
            pass
    # Primary: dateparser DMY es/en/pt
    try:
        _dp = _load_dateparser()
        if _dp is None:
            raise ModuleNotFoundError("dateparser")

        dp = _dp.parse(
            value,
            languages=["es", "en", "pt"],
            settings={"DATE_ORDER": "DMY", "PREFER_DAY_OF_MONTH": "first"},
        )
        if dp is not None:
            # normalize to naive datetime, guard year
            dp_naive = dp.replace(tzinfo=None) if dp.tzinfo else dp
            guarded = _year_guard(dp_naive)
            if guarded:
                return guarded
            # year outside window → fall through to allow None, don't return unguarded
            if dp.year < 2024 or dp.year > 2028:
                return None
            return dp_naive
    except Exception:
        pass
    # Fallback regex (kept for deterministic offline path)
    # 1. ISO format: 2027-06-30
    iso_match = _ISO_DATE.search(value)
    if iso_match:
        try:
            return _year_guard(datetime.strptime(iso_match.group(1), "%Y-%m-%d"))
        except ValueError:
            pass
    # 2. Slash format: 30/06/2027 or 06/30/2027.
    # DMY first: sources are predominantly es/pt, and an ambiguous date such as
    # 01/04/2026 must read as 1 April, matching the DATE_ORDER=DMY above.
    slash_match = _SLASH_DATE.search(value)
    if slash_match:
        for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
            try:
                return _year_guard(datetime.strptime(slash_match.group(1), fmt))
            except ValueError:
                continue
    # 2b. Dash format read as DMY: 15-03-2026 (MDY only as a salvage pass)
    dash_match = _DASH_DATE.search(value)
    if dash_match:
        for fmt in ("%d-%m-%Y", "%m-%d-%Y"):
            try:
                return _year_guard(datetime.strptime(dash_match.group(1), fmt))
            except ValueError:
                continue
    # 3. English: "June 30, 2027" or "Jun 30, 2027"
    eng_match = _ENGLISH_DATE.search(value)
    if eng_match:
        candidate = f"{eng_match.group(1).title()} {eng_match.group(2)}, {eng_match.group(3)}"
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return _year_guard(datetime.strptime(candidate, fmt))
            except ValueError:
                continue
    # 4. Spanish comma: "junio 30, 2027"
    es_comma = _SPANISH_DATE_COMMA.search(value)
    if es_comma:
        result = _parse_spanish_month(text, 1, 2, 3, es_comma)
        if result:
            return _year_guard(result)
    # 5. Spanish day-month-year with optional "de": "30 de junio de 2027", "30 abril 2026"
    es_flex = _SPANISH_DATE_FLEX.search(value)
    if es_flex:
        result = _parse_spanish_month(text, 2, 1, 3, es_flex)
        if result:
            return _year_guard(result)
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
        # Portuguese: "investimento: R$ 500.000" / "valor: R$ 500.000"
        r"(?:investimento|valor|recursos|aporte|orçamento|orçamento|custeio|subvenção|subvencao)\s*(?:total|estimado|disponivel|disponível|maximo|máximo|solicitado)?\s*[:\-]?\s*([\w\s.$€£,]+?\d[\d.,\s]*(?:million|milhão|milhões|mil|m|k|brl|usd|eur)?)",
        # Portuguese: "bolsa: R$ 5.000,00" (scholarship/stipend patterns)
        r"(?:bolsa|auxilio|auxílio|ajuda\s+de\s+custo|salário|salario|stipend)\s*(?::|de|)\s*(?:R?\$[\s\d.,]+)",
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
        r"(BRL\s*[\d.,]{3,})",
        r"(COP\s*[\$\s]*[\d.,]{3,})",
        r"\$(\d[\d.,]{2,}\s*(?:COP|USD|EUR)?)",
    ]
    for pattern in tier2:
        match = re.search(pattern, _text, flags=re.IGNORECASE)
        if match:
            result = match.group(1).strip()
            # Reject single/double-digit values (likely page numbers, counts)
            digits_only = re.sub(r"[^\d]", "", result)
            if (
                digits_only
                and int(digits_only) < 500
                and not re.search(r"(?:USD|EUR|COP|BRL|GBP)", result, re.IGNORECASE)
            ):
                continue
            return result

    return None


# ── Funding normalization ─────────────────────────────────────────────────

# Matched against normalize_text() output, so patterns are accent-free.
# Ordered most-specific-first: "mil millones" must win over "millones"/"mil".
_FUNDING_MAGNITUDES: tuple[tuple[str, float], ...] = (
    (r"mil\s+millones|mil\s+milhoes|billion|billon|bilhoes|bilhao", 1e9),
    (r"millones|millon|milhoes|milhao|million", 1e6),
    (r"\bmil\b|thousand", 1e3),
)

# ISO currency detection, most-specific-first. A bare "$" or an unqualified
# "pesos" is deliberately absent: the country/URL-based inference downstream
# resolves those, and guessing here would be wrong more often than right.
_FUNDING_CURRENCIES: tuple[tuple[str, str], ...] = (
    ("BRL", r"r\$|\breais\b|\bbrl\b"),
    ("COP", r"pesos?\s+colombianos?|\bcop\b|col\$"),
    ("MXN", r"pesos?\s+mexicanos?|\bmxn\b|mx\$"),
    ("CLP", r"pesos?\s+chilenos?|\bclp\b"),
    ("ARS", r"pesos?\s+argentinos?|\bars\b"),
    ("UYU", r"pesos?\s+uruguayos?|\buyu\b"),
    ("PEN", r"\bsoles\b|\bpen\b|s/\."),
    ("EUR", r"€|\beuros?\b|\beur\b"),
    ("GBP", r"£|\blibras?\b|\bgbp\b"),
    ("USD", r"\busd\b|us\$|\bdolares?\b|\bdollars?\b"),
)

_FUNDING_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_FUNDING_THOUSANDS_COMMA = re.compile(r"\d{1,3}(?:,\d{3})+")
_FUNDING_THOUSANDS_DOT = re.compile(r"\d{1,3}(?:\.\d{3})+")
# A range continuation immediately after the matched raw amount, e.g. the
# "- 1,000,000" in "USD 100,000 - 1,000,000".
_FUNDING_RANGE_TAIL = re.compile(
    r"^\s*(?:-|–|—|a|to|hasta|ate|até|y)\s*"
    r"(?:(?:USD|EUR|COP|BRL|GBP|MXN|CLP|PEN|ARS|UYU|R\$|US\$|\$|€|£)\s*)?\d[\d.,]*",
    flags=re.IGNORECASE,
)
_FUNDING_CONTEXT_AFTER = 48
_FUNDING_CONTEXT_BEFORE = 16


def _funding_number_to_float(token: str) -> float | None:
    """Convert one numeric token to a float, honouring both locale styles.

    ``50,000.00`` (en) and ``50.000,00`` (es) both yield ``50000.0``. When
    both separators appear, the last one is the decimal separator.
    """
    value = token.strip()
    if not value or not any(ch.isdigit() for ch in value):
        return None
    last_dot = value.rfind(".")
    last_comma = value.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        if last_dot > last_comma:
            value = value.replace(",", "")
        else:
            value = value.replace(".", "").replace(",", ".")
    elif last_comma >= 0:
        if _FUNDING_THOUSANDS_COMMA.fullmatch(value):
            value = value.replace(",", "")
        else:
            value = value.replace(",", ".")
    elif last_dot >= 0 and _FUNDING_THOUSANDS_DOT.fullmatch(value):
        value = value.replace(".", "")
    try:
        return float(value)
    except ValueError:
        return None


def _apply_funding_magnitude(value: float, normalized_context: str) -> float:
    """Scale a bare number by a nearby magnitude word (mil / millones / billion).

    The guards keep an already-scaled figure from being multiplied again, so
    "2.500.000 milhões" stays 2_500_000 rather than exploding.
    """
    for pattern, multiplier in _FUNDING_MAGNITUDES:
        if not re.search(pattern, normalized_context):
            continue
        if multiplier >= 1e6 and value >= 1000:
            return value
        if multiplier == 1e3 and value >= 1e6:
            return value
        return value * multiplier
    return value


def _detect_funding_currency(normalized_context: str) -> str | None:
    """Return the ISO 4217 code implied by the context, or None if ambiguous."""
    for iso_code, pattern in _FUNDING_CURRENCIES:
        if re.search(pattern, normalized_context):
            return iso_code
    return None


def extract_funding_details(text: str) -> tuple[str | None, float | None, str | None]:
    """Extract ``(raw, value, currency_iso)`` for a funding amount.

    ``raw`` comes from :func:`extract_funding_amount` (extended to cover the
    whole range when the amount is the low end of one). ``value`` is the
    numeric amount — the maximum for a range, since that is the headline
    "up to" figure. ``currency_iso`` is None when the text is ambiguous
    (bare ``$``, unqualified "pesos"); country-based inference downstream
    resolves those. Returns ``(None, None, None)`` when nothing is found.
    """
    if not text or not isinstance(text, str):
        return None, None, None
    try:
        raw = extract_funding_amount(text)
    except Exception:
        return None, None, None
    if not raw:
        return None, None, None

    source = text[:3000]
    start = source.find(raw)
    if start < 0:
        start = source.lower().find(raw.lower())
    if start >= 0:
        end = start + len(raw)
        tail = _FUNDING_RANGE_TAIL.match(source[end:])
        if tail:
            end += tail.end()
            raw = source[start:end].strip() or raw
        context = source[max(0, start - _FUNDING_CONTEXT_BEFORE) : end + _FUNDING_CONTEXT_AFTER]
    else:
        context = raw

    normalized = normalize_text(context)
    numbers = [
        parsed
        for parsed in (_funding_number_to_float(m.group(0)) for m in _FUNDING_NUMBER.finditer(raw))
        if parsed is not None
    ]
    value = _apply_funding_magnitude(max(numbers), normalized) if numbers else None
    return raw, value, _detect_funding_currency(normalized)


# ── Narrative section extraction ──────────────────────────────────────────

_ELIGIBILITY_LABELS: tuple[str, ...] = (
    "quién puede participar",
    "quienes pueden participar",
    "dirigido a",
    "perfil del participante",
    "población objetivo",
    "beneficiarios",
    "criterios de elegibilidad",
    "elegibilidad",
    "who can apply",
    "eligible applicants",
    "who is eligible",
    "eligibility",
    "quem pode participar",
    "público-alvo",
)

_REQUIREMENTS_LABELS: tuple[str, ...] = (
    "requisitos de participación",
    "condiciones de participación",
    "requisitos mínimos",
    "requisitos obrigatórios",
    "requisitos",
    "eligibility requirements",
    "requirements",
)

_DOCUMENTS_LABELS: tuple[str, ...] = (
    "documentos requeridos",
    "documentos a presentar",
    "documentos necesarios",
    "documentos necessários",
    "documentación",
    "anexos",
    "required documents",
    "documentation",
)

_EVALUATION_LABELS: tuple[str, ...] = (
    "criterios de evaluación",
    "criterios de selección",
    "criterios de calificación",
    "evaluación de propuestas",
    "evaluation criteria",
    "selection criteria",
    "assessment criteria",
    "critérios de avaliação",
)

_RESTRICTIONS_LABELS: tuple[str, ...] = (
    "restricciones",
    "no podrán participar",
    "no aplica",
    "exclusiones",
    "inhabilidades",
    "limitaciones",
    "restrictions",
    "exclusions",
    "ineligible",
    "not eligible",
    "restrições",
)

# Every known heading, used to detect where a captured section must stop.
_SECTION_HEADINGS: tuple[str, ...] = tuple(
    dict.fromkeys(
        normalize_text(label)
        for label in (
            *_ELIGIBILITY_LABELS,
            *_REQUIREMENTS_LABELS,
            *_DOCUMENTS_LABELS,
            *_EVALUATION_LABELS,
            *_RESTRICTIONS_LABELS,
        )
    )
)

# Bullet / enumeration marker at a line start or after whitespace.
_ITEM_SPLIT = re.compile(
    r"(?:^|\n|(?<=\s))"
    r"(?:[•▪·‣◦*]|[-–—](?=\s)|\(?(?:\d{1,2}|[a-z]|i{2,3}|iv|vi{1,3}|ix|xi{0,2})[.)])"
    r"\s+",
    flags=re.IGNORECASE | re.MULTILINE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+")
_PARAGRAPH_BREAK = re.compile(r"\n[^\S\n]*\n")
_LEADING_SEPARATORS = re.compile(r"^[\s:;.?!¿»\u2013\u2014]+")
_ITEM_TRIM = re.compile(r"^[\s\-–—•▪·‣◦*)\].]+|[\s;,:]+$")

_SECTION_MIN_ITEM_CHARS = 3


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    """Accent-folded lowercase view of ``text`` plus a per-char index map.

    Mirrors :func:`normalize_text` character by character so a match found in
    the normalized view can be mapped back to the original slice.
    """
    folded: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        for piece in unicodedata.normalize("NFKD", char):
            if unicodedata.combining(piece):
                continue
            folded.append(piece.lower())
            offsets.append(index)
    return "".join(folded), offsets


def _split_section_items(content: str) -> list[str]:
    """Split section content on bullet markers, else on sentence boundaries."""
    parts = [part for part in _ITEM_SPLIT.split(content) if part and part.strip()]
    if len(parts) < 2:
        parts = [part for part in _SENTENCE_SPLIT.split(content) if part and part.strip()]
    return parts


def extract_labeled_section(
    text: str,
    labels: Sequence[str],
    *,
    max_items: int = 12,
    max_chars: int = 400,
) -> list[str]:
    """Extract the list of items that follow a labelled heading.

    Matching is case- and accent-insensitive. The captured content runs from
    the label to the next known section heading, a paragraph break, or
    ``max_chars`` — whichever comes first. It is then split into items on
    bullet/enumeration markers when present and on sentence boundaries
    otherwise. Returns ``[]`` when the label is absent or nothing survives
    the noise/length filters.
    """
    if not text or not isinstance(text, str) or not labels:
        return []
    try:
        source = html.unescape(text)
        folded, offsets = _normalized_with_offsets(source)
        if not folded:
            return []

        normalized_labels = [normalize_text(label) for label in labels if label]
        best: tuple[int, int] | None = None
        for label in normalized_labels:
            position = folded.find(label)
            if position < 0:
                continue
            # Earliest occurrence wins; on a tie prefer the more specific label.
            if (
                best is None
                or position < best[0]
                or (position == best[0] and len(label) > best[1])
            ):
                best = (position, len(label))
        if best is None:
            return []

        start = best[0] + best[1]
        leading = _LEADING_SEPARATORS.match(folded[start:])
        if leading:
            start += leading.end()
        end = min(len(folded), start + max_chars)

        own_labels = set(normalized_labels)
        for heading in _SECTION_HEADINGS:
            if heading in own_labels:
                continue
            # +1 so content that itself opens with a heading phrase (e.g.
            # "No podrán participar ...") is not truncated to nothing.
            position = folded.find(heading, start + 1, end)
            if position > start:
                end = position
        paragraph = _PARAGRAPH_BREAK.search(folded, start, end)
        if paragraph:
            end = paragraph.start()
        if end <= start:
            return []

        content = source[offsets[start] : offsets[end] if end < len(offsets) else len(source)]
        content = content[:max_chars]

        items: list[str] = []
        seen: set[str] = set()
        for part in _split_section_items(content):
            item = clean_text(_ITEM_TRIM.sub("", part))
            if len(item) < _SECTION_MIN_ITEM_CHARS or len(item) > max_chars:
                continue
            if looks_like_noise_text(item):
                continue
            key = normalize_text(item)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []


def extract_eligibility(text: str) -> list[str]:
    """Who may apply to the call."""
    return extract_labeled_section(text, _ELIGIBILITY_LABELS)


def extract_requirements(text: str) -> list[str]:
    """Participation requirements."""
    return extract_labeled_section(text, _REQUIREMENTS_LABELS)


def extract_documents_required(text: str) -> list[str]:
    """Documents an applicant must submit."""
    return extract_labeled_section(text, _DOCUMENTS_LABELS)


def extract_evaluation_criteria(text: str) -> list[str]:
    """Criteria used to evaluate or select proposals."""
    return extract_labeled_section(text, _EVALUATION_LABELS)


def extract_restrictions(text: str) -> list[str]:
    """Exclusions, restrictions and disqualifying conditions."""
    return extract_labeled_section(text, _RESTRICTIONS_LABELS)


# ── Application URL detection ─────────────────────────────────────────────

# Accent-free stems, matched against normalize_text() output.
_APPLY_KEYWORDS: tuple[str, ...] = (
    "postul",
    "aplica",
    "inscrib",
    "inscri",
    "inscrev",
    "registrar",
    "participar",
    "convocatoria abierta",
    "formulario",
    "apply",
    "submit",
    "application",
    "register",
    "candidat",
)

# Hosts that only ever serve application forms — trusted across domains.
_FORM_HOSTS: tuple[str, ...] = (
    "docs.google.com/forms",
    "forms.gle",
    "forms.office.com",
    "typeform.com",
    "surveymonkey",
    "jotform",
    "smapply",
    "submittable",
    "fluidreview",
)

_SKIPPED_HREF_SCHEMES: tuple[str, ...] = ("mailto:", "tel:", "javascript:", "#")

# Two-level public suffixes common in LatAm, so "fondo.gov.co" is not read as
# the registrable domain "gov.co".
_TWO_LEVEL_SUFFIXES: frozenset[str] = frozenset(
    {
        "com",
        "gov",
        "gob",
        "org",
        "net",
        "edu",
        "co",
        "ac",
        "mil",
        "int",
        "nom",
        "web",
    }
)

_APPLY_SCORE_TEXT = 6
_APPLY_SCORE_TITLE = 4
_APPLY_SCORE_HREF = 3
_APPLY_SCORE_FORM_HOST = 8
_APPLY_SCORE_SAME_DOMAIN = 2
_APPLY_SCORE_OFFSITE_PENALTY = 4
_APPLY_SCORE_THRESHOLD = 5


def _registrable_domain(url: str) -> str:
    """Best-effort registrable domain ("sub.fondo.gov.co" → "fondo.gov.co")."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    labels = [label for label in host.split(".") if label]
    if len(labels) < 3:
        return ".".join(labels)
    if labels[-2] in _TWO_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _matches_apply_keyword(value: str) -> bool:
    normalized = normalize_text(value)
    return any(keyword in normalized for keyword in _APPLY_KEYWORDS)


def extract_application_url(html_or_tree: object, base_url: str) -> str | None:
    """Find the most likely "apply here" link on a page.

    Accepts raw HTML (parsed with selectolax) or an already-parsed tree, and
    scores every anchor by its text, ``title`` and ``href``. Well-known form
    hosts and same-registrable-domain links are preferred. Returns an
    absolute URL, or None when no plausible candidate exists.
    """
    if html_or_tree is None or not base_url:
        return None
    try:
        if hasattr(html_or_tree, "css"):
            tree = html_or_tree
        else:
            if not isinstance(html_or_tree, str) or not html_or_tree.strip():
                return None
            from selectolax.parser import HTMLParser

            tree = HTMLParser(html_or_tree)

        base_domain = _registrable_domain(base_url)
        best_url: str | None = None
        best_score = 0
        for anchor in tree.css("a"):
            href = (anchor.attributes.get("href") or "").strip()
            if not href:
                continue
            lowered_href = href.lower()
            if lowered_href.startswith(_SKIPPED_HREF_SCHEMES):
                continue
            absolute = safe_urljoin(base_url, href)
            if not absolute.lower().startswith(("http://", "https://")):
                continue

            normalized_absolute = normalize_text(absolute)
            is_form_host = any(host in normalized_absolute for host in _FORM_HOSTS)
            score = 0
            if _matches_apply_keyword(anchor.text() or ""):
                score += _APPLY_SCORE_TEXT
            if _matches_apply_keyword(anchor.attributes.get("title") or ""):
                score += _APPLY_SCORE_TITLE
            if _matches_apply_keyword(href):
                score += _APPLY_SCORE_HREF
            if is_form_host:
                score += _APPLY_SCORE_FORM_HOST
            if base_domain and _registrable_domain(absolute) == base_domain:
                score += _APPLY_SCORE_SAME_DOMAIN
            elif not is_form_host:
                score -= _APPLY_SCORE_OFFSITE_PENALTY

            if score > best_score:
                best_score = score
                best_url = absolute
        return best_url if best_score >= _APPLY_SCORE_THRESHOLD else None
    except Exception:
        return None


# ── Consolidated structured data (JSON-LD → microdata → OpenGraph) ────────

_STRUCTURED_KEYS: tuple[str, ...] = (
    "title",
    "summary",
    "open_date",
    "close_date",
    "funding_raw",
    "funding_value",
    "funding_currency",
    "application_url",
    "categories",
    "eligible_applicants",
)

_STRUCTURED_TITLE_KEYS = ("name", "title", "headline")
_STRUCTURED_SUMMARY_KEYS = ("description", "summary", "abstract")
_STRUCTURED_OPEN_KEYS = ("startdate", "validfrom", "opendate", "start_date")
_STRUCTURED_CLOSE_KEYS = (
    "enddate",
    "closedate",
    "deadline",
    "validthrough",
    "close_date",
    "applicationdeadline",
)
_STRUCTURED_FUNDING_KEYS = ("funding", "fundingamount", "amount")
_STRUCTURED_URL_KEYS = ("url", "applicationurl")
_STRUCTURED_CATEGORY_KEYS = ("keywords", "about", "category")
_STRUCTURED_AUDIENCE_KEYS = ("eligibleapplicant", "eligibleapplicants", "audience")

_STRUCTURED_LIST_SPLIT = re.compile(r"[,;|]")
_STRUCTURED_URL_ATTR_TAGS = frozenset({"a", "link", "area", "img", "source"})


def _structured_skeleton() -> dict[str, object]:
    result: dict[str, object] = dict.fromkeys(_STRUCTURED_KEYS)
    result["categories"] = []
    result["eligible_applicants"] = []
    return result


def _as_text_list(value: object) -> list[str]:
    """Flatten a schema.org string / list / node value into a list of strings."""
    collected: list[str] = []
    if isinstance(value, str):
        collected.extend(part.strip() for part in _STRUCTURED_LIST_SPLIT.split(value))
    elif isinstance(value, dict):
        name = value.get("name") or value.get("title")
        if isinstance(name, str):
            collected.append(name.strip())
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            collected.extend(_as_text_list(item))
    elif value is not None and not isinstance(value, bool):
        collected.append(str(value).strip())
    unique: list[str] = []
    seen: set[str] = set()
    for item in collected:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _parse_structured_date(value: object, *, is_open: bool) -> datetime | None:
    if value is None:
        return None
    text = clean_text(str(value))
    if not text:
        return None
    parsed = parse_date_text(text)
    if parsed:
        return parsed
    return extract_open_date(text) if is_open else extract_close_date(text)


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _funding_number_to_float(value.strip())
    return None


def _assign_structured_funding(result: dict[str, object], value: object) -> None:
    """Fill the funding_* keys from a JSON-LD/microdata funding value."""
    if result["funding_raw"] is not None or result["funding_value"] is not None:
        return
    if isinstance(value, dict):
        lowered = {str(key).lower(): item for key, item in value.items()}
        nested = (
            lowered.get("value")
            if lowered.get("value") is not None
            else lowered.get("amount")
            if lowered.get("amount") is not None
            else lowered.get("maxvalue")
        )
        if isinstance(nested, dict):
            _assign_structured_funding(result, nested)
            return
        currency = (
            lowered.get("currency") or lowered.get("currencycode") or lowered.get("pricecurrency")
        )
        numeric = _to_float(nested)
        if numeric is not None:
            iso = str(currency).strip().upper()[:3] if currency else None
            result["funding_value"] = numeric
            result["funding_currency"] = iso or None
            result["funding_raw"] = f"{nested} {iso}".strip() if iso else str(nested)
        return
    text = clean_text(str(value)) if value is not None else ""
    if not text:
        return
    raw, numeric, currency = extract_funding_details(text)
    result["funding_raw"] = raw or text[:200]
    result["funding_value"] = numeric
    result["funding_currency"] = currency


def _iter_jsonld_items(payload: object):
    """Yield every mapping in a JSON-LD payload, descending into @graph."""
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, (list, tuple)):
            for item in graph:
                yield from _iter_jsonld_items(item)
        yield payload
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            yield from _iter_jsonld_items(item)


def _first_value(item: dict[str, object], keys: tuple[str, ...]) -> object:
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        value = lowered.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _apply_structured_item(
    result: dict[str, object], item: dict[str, object], base_url: str | None
) -> None:
    """Merge one property mapping into ``result``, never overwriting a hit."""
    if result["title"] is None:
        title = _first_value(item, _STRUCTURED_TITLE_KEYS)
        if isinstance(title, str) and clean_text(title):
            result["title"] = clean_text(title)
    if result["summary"] is None:
        summary = _first_value(item, _STRUCTURED_SUMMARY_KEYS)
        if isinstance(summary, str) and clean_text(summary):
            result["summary"] = clean_text(summary)
    if result["open_date"] is None:
        result["open_date"] = _parse_structured_date(
            _first_value(item, _STRUCTURED_OPEN_KEYS), is_open=True
        )
    if result["close_date"] is None:
        result["close_date"] = _parse_structured_date(
            _first_value(item, _STRUCTURED_CLOSE_KEYS), is_open=False
        )
    _assign_structured_funding(result, _first_value(item, _STRUCTURED_FUNDING_KEYS))
    if result["application_url"] is None:
        url_value = _first_value(item, _STRUCTURED_URL_KEYS)
        if isinstance(url_value, dict):
            url_value = url_value.get("url")
        if isinstance(url_value, str) and url_value.strip():
            candidate = url_value.strip()
            absolute = safe_urljoin(base_url, candidate) if base_url else candidate
            if absolute.lower().startswith(("http://", "https://")):
                result["application_url"] = absolute
    if not result["categories"]:
        result["categories"] = _as_text_list(_first_value(item, _STRUCTURED_CATEGORY_KEYS))
    if not result["eligible_applicants"]:
        result["eligible_applicants"] = _as_text_list(
            _first_value(item, _STRUCTURED_AUDIENCE_KEYS)
        )


def extract_structured_data(html: str, base_url: str | None = None) -> dict[str, object]:
    """Read JSON-LD, microdata and OpenGraph into one normalized dict.

    Priority is JSON-LD → microdata → OpenGraph/meta: a value found by an
    earlier source is never overwritten by a later one. Malformed JSON-LD is
    skipped silently. Always returns every key in ``_STRUCTURED_KEYS``.
    """
    result = _structured_skeleton()
    if not html or not isinstance(html, str):
        return result
    try:
        import json as _json

        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)

        for script in tree.css("script[type='application/ld+json']"):
            try:
                payload = _json.loads(script.text() or "")
            except Exception:
                continue
            for item in _iter_jsonld_items(payload):
                _apply_structured_item(result, item, base_url)

        microdata: dict[str, object] = {}
        for node in tree.css("[itemprop]"):
            prop = (node.attributes.get("itemprop") or "").strip().lower()
            if not prop or prop in microdata:
                continue
            value = node.attributes.get("content")
            if value is None and node.tag in _STRUCTURED_URL_ATTR_TAGS:
                value = node.attributes.get("href") or node.attributes.get("src")
            if value is None:
                value = node.text()
            value = clean_text(value)
            if value:
                microdata[prop] = value
        if microdata:
            _apply_structured_item(result, microdata, base_url)

        if result["title"] is None:
            node = tree.css_first("meta[property='og:title']")
            title = clean_text(node.attributes.get("content") if node else None)
            if title:
                result["title"] = title
        if result["summary"] is None:
            for selector in ("meta[property='og:description']", "meta[name='description']"):
                node = tree.css_first(selector)
                summary = clean_text(node.attributes.get("content") if node else None)
                if summary:
                    result["summary"] = summary
                    break
        if result["application_url"] is None and base_url:
            result["application_url"] = extract_application_url(tree, base_url)
    except Exception:
        return result
    return result


_RAW_TEXT_LIMIT = 15000
_SUMMARY_LIMIT = 1200
_DESCRIPTION_LIMIT = 4000

_NARRATIVE_EXTRACTORS: tuple[tuple[str, object], ...] = (
    ("eligible_applicants", extract_eligibility),
    ("requirements", extract_requirements),
    ("documents_required", extract_documents_required),
    ("evaluation_criteria", extract_evaluation_criteria),
    ("restrictions", extract_restrictions),
)


def _node_visible_text(node: object) -> str:
    if node is None:
        return ""
    try:
        return (node.text(separator="\n") or "").strip()  # type: ignore[union-attr]
    except TypeError:
        return ((node.text() if hasattr(node, "text") else "") or "").strip()


def _prefer_longer_text(current: str | None, incoming: str | None) -> str:
    left = (current or "").strip()
    right = (incoming or "").strip()
    if not right:
        return left
    if not left:
        return right
    return right if len(right) > len(left) else left


def extract_page_fields(
    *,
    html: str | None = None,
    text: str | None = None,
    page_url: str | None = None,
) -> dict[str, object]:
    """Pull every opportunity field we can read from a page.

    Combines JSON-LD/microdata/OpenGraph with the labelled-section, date and
    funding extractors. Missing values are ``None`` or ``[]`` — never inferred
    from another field. Safe on empty or malformed input.
    """
    result: dict[str, object] = {
        "title": None,
        "summary": None,
        "description": None,
        "open_date": None,
        "close_date": None,
        "funding_amount_raw": None,
        "funding_amount_value": None,
        "funding_amount_currency": None,
        "application_url": None,
        "categories": [],
        "eligible_applicants": [],
        "requirements": [],
        "documents_required": [],
        "evaluation_criteria": [],
        "restrictions": [],
        "raw_text": None,
    }
    page_text = text or ""
    if html and isinstance(html, str):
        structured = extract_structured_data(html, page_url)
        if structured.get("title"):
            result["title"] = structured["title"]
        if structured.get("summary"):
            result["summary"] = structured["summary"]
        if structured.get("open_date") is not None:
            result["open_date"] = structured["open_date"]
        if structured.get("close_date") is not None:
            result["close_date"] = structured["close_date"]
        if structured.get("funding_raw"):
            result["funding_amount_raw"] = structured["funding_raw"]
        if structured.get("funding_value") is not None:
            result["funding_amount_value"] = structured["funding_value"]
        if structured.get("funding_currency"):
            result["funding_amount_currency"] = structured["funding_currency"]
        if structured.get("application_url"):
            result["application_url"] = structured["application_url"]
        if structured.get("categories"):
            result["categories"] = list(structured["categories"] or [])
        if structured.get("eligible_applicants"):
            result["eligible_applicants"] = list(structured["eligible_applicants"] or [])
        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(html)
            if result["title"] is None:
                heading = tree.css_first("h1")
                heading_text = clean_text(_node_visible_text(heading)) if heading else ""
                if heading_text:
                    result["title"] = heading_text[:180]
            for selector in ("article", "main", "[role='main']", ".content", "#content", "body"):
                node = tree.css_first(selector)
                extracted = _node_visible_text(node)
                if len(extracted) > len(page_text):
                    page_text = extracted
        except Exception:
            if not page_text:
                page_text = html

    if page_text:
        if result["open_date"] is None:
            result["open_date"] = extract_open_date(page_text)
        if result["close_date"] is None:
            result["close_date"] = extract_close_date(page_text)
        raw, value, currency = extract_funding_details(page_text)
        if result["funding_amount_raw"] is None:
            raw = raw or extract_funding_amount(page_text)
        if result["funding_amount_raw"] is None and raw:
            result["funding_amount_raw"] = raw
        if result["funding_amount_value"] is None and value is not None:
            result["funding_amount_value"] = value
        if result["funding_amount_currency"] is None and currency:
            result["funding_amount_currency"] = currency
        for key, extractor in _NARRATIVE_EXTRACTORS:
            if result[key]:
                continue
            try:
                items = list(extractor(page_text) or [])
            except Exception:
                items = []
            if items:
                result[key] = items
        if result["summary"] is None:
            collapsed = clean_text(page_text)
            if collapsed and not looks_like_noise_text(collapsed):
                result["summary"] = collapsed[:_SUMMARY_LIMIT]
        if result["description"] is None:
            collapsed = clean_text(page_text)
            if collapsed:
                result["description"] = collapsed[:_DESCRIPTION_LIMIT]
        result["raw_text"] = page_text[:_RAW_TEXT_LIMIT]

    if result["application_url"] is None and html and page_url:
        result["application_url"] = extract_application_url(html, page_url)
    return result


def apply_extracted_fields(
    candidate: OpportunityCandidate,
    extracted: dict[str, object],
    *,
    prefer_extracted_text: bool = False,
) -> OpportunityCandidate:
    """Copy extracted fields onto ``candidate``, filling gaps only by default.

    When ``prefer_extracted_text`` is true (detail-page merge), a longer
    incoming title/summary/description/raw_text replaces the list-card snippet.
    Existing non-empty dates, funding and narrative lists are never overwritten.
    """
    from dataclasses import replace

    updates: dict[str, object] = {}

    extra_title = extracted.get("title")
    if isinstance(extra_title, str) and extra_title.strip():
        if not candidate.title or (prefer_extracted_text and len(extra_title) > len(candidate.title)):
            updates["title"] = extra_title.strip()[:180]

    for text_key in ("summary", "description", "raw_text"):
        incoming = extracted.get(text_key)
        if not isinstance(incoming, str) or not incoming.strip():
            continue
        current = getattr(candidate, text_key) or ""
        if current and not prefer_extracted_text:
            continue
        chosen = _prefer_longer_text(current, incoming) if prefer_extracted_text else incoming.strip()
        if chosen and chosen != current:
            limit = _RAW_TEXT_LIMIT if text_key == "raw_text" else (
                _DESCRIPTION_LIMIT if text_key == "description" else _SUMMARY_LIMIT
            )
            updates[text_key] = chosen[:limit]

    for key in (
        "open_date",
        "close_date",
        "funding_amount_raw",
        "funding_amount_value",
        "funding_amount_currency",
        "application_url",
        "region",
        "external_id",
    ):
        if getattr(candidate, key, None) not in (None, ""):
            continue
        value = extracted.get(key)
        if value not in (None, ""):
            updates[key] = value

    for key in (
        "eligible_applicants",
        "requirements",
        "documents_required",
        "evaluation_criteria",
        "restrictions",
        "categories",
        "topics",
    ):
        current = getattr(candidate, key, None) or []
        incoming = extracted.get(key) or []
        if not current and incoming:
            updates[key] = list(incoming)

    return replace(candidate, **updates) if updates else candidate


def fill_candidate_from_content(
    candidate: OpportunityCandidate,
    *,
    html: str | None = None,
    text: str | None = None,
    page_url: str | None = None,
) -> OpportunityCandidate:
    """Fill missing candidate fields from page HTML and/or visible text."""
    extracted = extract_page_fields(html=html, text=text, page_url=page_url or candidate.official_url)
    return apply_extracted_fields(candidate, extracted)


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


# ── User-Agent rotation pool ────────────────────────────────────────────────

_UA_POOL: list[str] = [
    # Chrome 125+ (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Chrome 125+ (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox 127 (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Firefox 127 (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:127.0) Gecko/20100101 Firefox/127.0",
    # Edge 125 (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Safari 17.5 (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    # Chrome 125 (Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Mobile Chrome (Android)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]


def _random_user_agent() -> str:
    """Return a random User-Agent from the pool."""
    import random as _random

    return _random.choice(_UA_POOL)


def _resolve_proxy() -> str | None:
    """Pick a random proxy from the configured list, or None."""
    from app.core.config import get_settings as _settings

    proxies = _settings().scraping_proxy_list
    if not proxies:
        return None
    import random as _random

    return _random.choice(proxies)


# ── Date parsing constants ────────────────────────────────────────────────
_SPANISH_MONTHS: dict[str, int] = {
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

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_ENGLISH_DATE = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})\b")
_SPANISH_DATE_COMMA = re.compile(
    r"\b([A-Za-záéíóúñ]+)\s+(\d{1,2}),\s+(\d{4})\b", flags=re.IGNORECASE
)
_SPANISH_DATE_DE = re.compile(
    r"\b(\d{1,2})\s+de\s+([A-Za-záéíóúñ]+)\s+de\s+(\d{4})\b", flags=re.IGNORECASE
)
# Spanish day-month-year where the "de" connector is optional in both slots:
# "30 abril 2026", "30 de abril 2026", "30 abril de 2026", "30 de abril de 2026".
_SPANISH_DATE_FLEX = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?([A-Za-záéíóúñ]+),?\s+(?:de\s+)?(\d{4})\b", flags=re.IGNORECASE
)
# Dash-separated numeric dates are read as DMY, consistent with DATE_ORDER=DMY.
_DASH_DATE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b")

# Shared alternation of every date shape the tier patterns accept. ISO comes
# first so a full ISO date is never partially consumed by the numeric branch.
_DATE_VALUE_ALT = (
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{4}"
    r"|\d{1,2}\s+(?:de\s+)?[a-záéíóúñ]+,?\s+(?:de\s+)?\d{4}"
    r"|[a-záéíóúñ]+\s+\d{1,2},?\s+\d{4}"
)

# Tier-1 labelled open-date patterns (Spanish, English, Portuguese).
_OPEN_DATE_LABELS: tuple[str, ...] = (
    r"fecha\s+(?:de\s+)?apertura",
    r"apertura\s+(?:de\s+la\s+)?(?:convocatoria|postulaciones)",
    r"apertura",
    r"inicio\s+(?:de\s+(?:la\s+)?)?(?:convocatoria|postulaciones|inscripciones|recepcion|recepción)",
    r"fecha\s+de\s+inicio",
    r"inicio",
    r"abre\s+(?:el\s+)?(?:dia\s+|día\s+)?",
    r"desde\s+(?:el\s+)?(?:dia\s+|día\s+)?",
    r"disponible\s+a\s+partir\s+de(?:l)?",
    r"a\s+partir\s+de(?:l)?",
    r"opening\s+date",
    r"publication\s+date",
    r"start\s+date",
    r"opens(?:\s+on)?",
    r"data\s+(?:de\s+)?abertura",
    r"inscri[cç][oõ]es\s+a\s+partir\s+de",
)

_OPEN_DATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"(?:{label})\s*[:\-]?\s*({_DATE_VALUE_ALT})", flags=re.IGNORECASE)
    for label in _OPEN_DATE_LABELS
)

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
    request_headers = {"User-Agent": _random_user_agent()}
    if headers:
        request_headers.update(headers)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    request_timeout = min(timeout_seconds or settings.scraping_timeout_seconds, FETCH_TIMEOUT_CAP)

    # Per-domain budget check + burst accounting (023 S3)
    _budget = _get_budget()
    _delay = _budget.delay_for(url)
    if _delay > 0:
        import asyncio as _asyncio

        await _asyncio.sleep(_delay)
    _budget_acquired = _budget.acquire(url)
    if not _budget_acquired:
        raise RuntimeError(f"Domain budget exhausted for {url}")
    # burst window accounting — count toward throttle_max_per_day 150
    try:
        _budget.record_request(url)
    except Exception:
        pass

    try:
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(max(retries, 1)):
            try:
                proxy = _resolve_proxy()
                if proxy:
                    import httpx as _httpx

                    client = _httpx.AsyncClient(proxies=proxy, timeout=request_timeout)
                else:
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
                if not any(p in raw_ct for p in _JSON_CONTENT_PATTERNS) and _looks_like_json(
                    body_text
                ):
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
                # 429 backoff via DomainBudgetManager
                if exc.response.status_code == 429:
                    try:
                        from app.scraper.domain_budget import get_domain_budget

                        retry_after = exc.response.headers.get("Retry-After")
                        get_domain_budget().handle_429(url, retry_after)
                    except Exception:
                        pass
                # 403 JSON API: don't Playwright-fallback (wastes browser)
                ct = exc.response.headers.get("content-type", "")
                if exc.response.status_code == 403 and "json" in ct.lower():
                    raise
                if attempt + 1 >= retries:
                    break
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= retries:
                    break
        if not playwright_fallback:
            raise last_error or RuntimeError(f"Failed to fetch {url}")
        # 403 JSON API already raised above; remaining 4xx JSON should not fallback
        if last_status == 403 and last_error is not None:
            try:
                if "json" in str(getattr(getattr(last_error, "response", None), "headers", {}).get("content-type", "")).lower():
                    raise last_error
            except Exception:
                pass
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
    """Fetch a detail page and extract every opportunity field we can read."""
    try:
        import asyncio as _asyncio

        _, content, _ct = await _asyncio.wait_for(
            fetch_httpx_text(
                url, timeout_seconds=DETAIL_PAGE_TIMEOUT, retries=1, playwright_fallback=True
            ),
            timeout=DETAIL_PAGE_TIMEOUT + 10,
        )
    except Exception:
        return None

    result = extract_page_fields(html=content, page_url=url)
    return result if result.get("title") else None


# ── Title cleanup ───────────────────────────────────────────────────────────


def clean_opportunity_title(title: str | None, max_len: int = 150) -> str:
    """Clean and truncate opportunity titles.

    Removes verbose suffixes common in Brazilian/LatAm portals:
    - ``Instituição: ...``
    - ``Cidade: ...``
    - ``Inscrições até: ...``
    - ``Fecha de cierre: ...``
    """
    if not title:
        return title or ""

    text = title.strip()
    if len(text) <= max_len:
        return text

    # Remove verbose Portuguese/Spanish suffixes
    for sep in (
        "Instituição:",
        "instituição:",
        "Cidade:",
        "cidade:",
        "Inscrições até:",
        "inscrições até:",
        "Inscricoes ate:",
        "Fecha de cierre:",
        "fecha de cierre:",
        "Deadline:",
        "Inscrições:",
        "inscrições:",
        "Instituição:",
        "instituição:",
    ):
        idx = text.find(sep)
        if idx > 20:  # Only if separator is past the first meaningful part
            text = text[:idx].strip()
            break

    # If still too long, smart truncate at last period/semicolon before max_len
    if len(text) > max_len:
        for sep_char in (".", ";", "|", "/"):
            truncated = text[:max_len]
            last_sep = truncated.rfind(sep_char)
            if last_sep > max_len // 2:
                return truncated[:last_sep].strip() + "."
        return text[:max_len].rsplit(" ", 1)[0] + "..."

    return text


# ── Country inference ───────────────────────────────────────────────────────


_COUNTRY_MAP: dict[str, str] = {
    # Domains → country
    "findeter.gov.co": "Colombia",
    "minciencias.gov.co": "Colombia",
    "icetex.gov.co": "Colombia",
    "apccolombia.gov.co": "Colombia",
    "procolombia.co": "Colombia",
    "colfuturo.org": "Colombia",
    "dane.gov.co": "Colombia",
    "sena.edu.co": "Colombia",
    "rutanmedellin.org": "Colombia",
    "ccb.org.co": "Colombia",
    "bancoldex.com": "Colombia",
    "unal.edu.co": "Colombia",
    "udea.edu.co": "Colombia",
    "innpulsacolombia.com": "Colombia",
    "artesaniasdecolombia.com.co": "Colombia",
    "fondoemprender.com": "Colombia",
    "fapesp.br": "Brazil",
    "finep.gov.br": "Brazil",
    "gov.br": "Brazil",
    "anp.gov.br": "Brazil",
    "faperj.br": "Brazil",
    "fapemig.br": "Brazil",
    "conicet.gov.ar": "Argentina",
    "anid.cl": "Chile",
    "conahcyt.mx": "Mexico",
    "gob.pe": "Peru",
    "conacyt.gov.py": "Paraguay",
    "nsf.gov": "United States",
    "grants.gov": "United States",
    "ukri.org": "United Kingdom",
    "wellcome.org": "United Kingdom",
    "ec.europa.eu": "European Union",
    "eufundingportal.eu": "European Union",
    "giz.de": "Germany",
    "dfg.de": "Germany",
    "sida.se": "Sweden",
    "norad.no": "Norway",
    "um.dk": "Denmark",
    "novonordiskfonden.dk": "Denmark",
    "lundbeckfonden.com": "Denmark",
    "veluxfonden.dk": "Denmark",
    "un.org": "International",
    "unesco.org": "International",
    "undp.org": "International",
    "thegef.org": "International",
    "greenclimate.fund": "International",
    "iadb.org": "International",
    "oei.int": "International",
    "cepal.org": "International",
    "segib.org": "International",
    "globalinnovation.fund": "International",
    "fordfoundation.org": "International",
    "rockefellerfoundation.org": "International",
    # Entities → country
    "findeter": "Colombia",
    "minciencias": "Colombia",
    "icetex": "Colombia",
    "apc colombia": "Colombia",
    "procolombia": "Colombia",
    "colfuturo": "Colombia",
    "dane": "Colombia",
    "sena": "Colombia",
    "innpulsa": "Colombia",
    "fondo emprender": "Colombia",
    "universidad nacional": "Colombia",
    "universidad de los andes": "Colombia",
    "uniandes": "Colombia",
    "fapesp": "Brazil",
    "finep": "Brazil",
    "cnpq": "Brazil",
    "capes": "Brazil",
    "conicet": "Argentina",
    "fondecyt": "Chile",
    "conahcyt": "Mexico",
    "concytec": "Peru",
    "bndes": "Brazil",
    "developmentaid": "International",
    "undef": "International",
    "un women": "International",
    "unesco": "International",
    "undp": "International",
    "ukri": "United Kingdom",
    "uk research and innovation": "United Kingdom",
    "wellcome trust": "United Kingdom",
    "wellcome": "United Kingdom",
    "horizon europe": "European Union",
    "eic accelerator": "European Union",
    "giz": "Germany",
    "cdti": "Spain",
    "isciii": "Spain",
    "aecid": "Spain",
}


def infer_country_from_entity(entity_name: str | None, official_url: str | None = None) -> str:
    """Infer country from entity name or domain.

    Returns a country string or "Por validar" if unrecognised.
    """
    # 1. Try domain first (most specific)
    if official_url:
        domain = official_url.lower()
        # Handle bare domains without scheme
        if not domain.startswith("http"):
            domain = "http://" + domain
        from urllib.parse import urlparse

        parsed = urlparse(domain)
        hostname = parsed.hostname or ""
        if hostname.startswith("www."):
            hostname = hostname[4:]
        # Check domain → country map
        for key, country in _COUNTRY_MAP.items():
            if key in hostname:
                return country

    # 2. Try entity name
    if entity_name:
        lower = entity_name.lower().strip()
        for key, country in _COUNTRY_MAP.items():
            if key in lower:
                return country

    return "Por validar"


async def enrich_candidates_batch(
    candidates: list[OpportunityCandidate],
    max_fetches: int | None = None,
) -> list[OpportunityCandidate]:
    """Batch-enrich low-confidence candidates by fetching detail pages.

    Fetches up to ``max_fetches`` detail pages concurrently, extracts
    close_date, funding_amount, and title, then returns an enriched
    copy of the full candidate list.
    """
    import asyncio
    from copy import deepcopy

    limit = max_fetches if max_fetches is not None else int(get_settings().extraction_detail_limit)
    to_enrich = candidates[:limit]
    tasks = {c.official_url: enrich_from_detail_page(c.official_url) for c in to_enrich}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    url_to_data: dict[str, dict | None] = {}
    for url, task in zip(tasks, results):
        url_to_data[url] = task if isinstance(task, dict) and task.get("title") else None

    enriched: list[OpportunityCandidate] = []
    for c in candidates:
        detail = url_to_data.get(c.official_url)
        if detail:
            merged = apply_extracted_fields(c, detail, prefer_extracted_text=True)
            from dataclasses import replace as _replace

            enriched.append(_replace(merged, confidence_score=0.82))
        else:
            enriched.append(deepcopy(c))
    return enriched
