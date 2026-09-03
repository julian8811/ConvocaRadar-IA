"""Enriquecer resumenes visitando la pagina oficial de cada convocatoria.

Dos vias segun el tipo de sitio:
  * Sitios SPA (grants.gov, simpler.grants.gov): render real con Playwright
    y lectura del texto del DOM (el HTML crudo viene vacio).
  * Resto: httpx con fallback a Playwright via fetch_httpx_text.

El texto se limpia con filtros de ruido (banners de gobierno, navegacion,
cookies, etc.) y se resumen las primeras oraciones sustanciales.

Reanudable: las filas ya reparadas dejan de calificar en la proxima corrida.

Usage:
    python scripts/scrape_missing_summaries.py                # todas
    python scripts/scrape_missing_summaries.py --limit 20     # lote chico
    python scripts/scrape_missing_summaries.py --dry-run      # sin escribir
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.connectors.common import CHROMIUM_CONTAINER_ARGS, fetch_httpx_text
from app.db.session import SessionLocal
from app.models import Opportunity

SPA_HOSTS = ("www.grants.gov", "grants.gov", "simpler.grants.gov")

NOISE_RE = re.compile(
    r"official website|here'?s how you know|belongs to an official|\.gov website|"
    r"javascript|enable |browser|cookie|privacy policy|skip to main|accessibility|"
    r"sign in|log ?in|newsletter|all rights reserved|copyright|©|terms of use|"
    r"menu |search |share |print |download |contact us\b|home\s*\||\bfaq\b",
    re.IGNORECASE,
)
META_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']{40,600})["\']',
    re.IGNORECASE,
)


LABEL_RE = re.compile(r"^[A-Z][A-Za-z ,''()/-]{2,60}:\s")


def is_thin_summary(summary: str | None) -> bool:
    s = (summary or "").strip()
    if len(s) < 120 or s.startswith("Convocatoria de "):
        return True
    # Banner/boilerplate al inicio: basura sin importar el largo.
    if re.match(
        r"^(an official website|here'?s how you know|official websites use)",
        s,
        re.IGNORECASE,
    ):
        return True
    # Volcado de formulario: varias etiquetas "Campo: valor" seguidas.
    if len(re.findall(r"[A-Za-z][A-Za-z ,''()/-]{2,48}:", s[:220])) >= 2:
        return True
    if NOISE_RE.search(s[:200]) and len(re.sub(r"\s+", " ", s)) < 260:
        return True
    return False


def _sentences(text: str) -> list[str]:
    # Si el documento trae seccion de descripcion, arrancar desde ahi.
    m = re.search(r"(?im)^\s*(?:grant\s+)?(?:opportunity\s+)?description\s*:?\s*$", text)
    if m:
        text = text[m.end():]
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out: list[str] = []
    for p in parts:
        clean = re.sub(r"\s+", " ", p).strip()
        if len(clean) < 60 or len(clean) > 500:
            continue
        if NOISE_RE.search(clean) or LABEL_RE.match(clean):
            continue
        if not re.search(r"[a-záéíóúñü]", clean, re.IGNORECASE):
            continue
        out.append(clean)
        if len(out) >= 4:
            break
    return out


def build_summary(raw_html_or_text: str, *, is_text: bool) -> str:
    """Resumen factual desde meta description o contenido filtrado."""
    if not is_text:
        m = META_DESC_RE.search(raw_html_or_text[:80000])
        meta_desc = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        import re as _re

        html = raw_html_or_text
        html = _re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html, flags=_re.S | _re.I)
        text = _re.sub(r"<[^>]+>", "\n", html)
        text = _re.sub(r"&nbsp;?", " ", text)
    else:
        meta_desc = ""
        text = raw_html_or_text
    sents = _sentences(text)
    if meta_desc and len(meta_desc) >= 80:
        return f"{meta_desc} {' '.join(sents[:1])}".strip()[:700]
    joined = " ".join(sents[:3]).strip()
    return joined[:700]


async def fetch_spa(url: str, browser) -> str:
    context = await browser.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)
        for sel in ("main", "article", "[id*='main']", "body"):
            loc = page.locator(sel).first
            if await loc.count():
                try:
                    txt = await loc.inner_text(timeout=8000)
                except Exception:
                    continue
                if len(txt.strip()) > 300:
                    return txt
        return ""
    finally:
        await context.close()


def save_summary(opp_id: str, summary: str, dry_run: bool) -> None:
    with SessionLocal() as db:
        opp = db.get(Opportunity, opp_id)
        if opp is None:
            return
        opp.summary = summary
        opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
        if not dry_run:
            db.commit()


async def process(opp_id: str, url: str, dry_run: bool, browser, results: dict, sem: asyncio.Semaphore):
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    async with sem:
        # Reintentar con paciencia: varios dominios admiten solo 2 slots
        # simultaneos y el presupuesto por dominio rechaza en frio.
        backoffs = (0, 2, 5, 10, 20, 35)
        summary = ""
        for attempt, wait in enumerate(backoffs):
            if wait:
                await asyncio.sleep(wait)
            try:
                if host in SPA_HOSTS:
                    text = await fetch_spa(url, browser)
                    summary = build_summary(text, is_text=True) if text else ""
                else:
                    _u, content, _ct = await fetch_httpx_text(
                        url, playwright_fallback=True, timeout_seconds=35, retries=1
                    )
                    summary = build_summary(content, is_text=False)
                break
            except Exception as exc:
                is_budget = "Domain budget exhausted" in str(exc)
                if not is_budget or attempt == len(backoffs) - 1:
                    results["failed"] += 1
                    return
    if len(summary) < 80:
        results["no_content"] += 1
        return
    await asyncio.to_thread(save_summary, opp_id, summary, dry_run)
    results["updated"] += 1


async def main_async(limit: int, dry_run: bool) -> None:
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(Opportunity.id, Opportunity.summary, Opportunity.official_url)
                .where(Opportunity.official_url.isnot(None), Opportunity.official_url != "")
                .order_by(Opportunity.created_at.desc())
            ).all()
        )
    targets = [(oid, url) for oid, s, url in rows if url and is_thin_summary(s)]
    if limit > 0:
        targets = targets[:limit]
    print(f"resumenes a enriquecer: {len(targets)}")
    if not targets:
        print("Nada por hacer.")
        return

    from playwright.async_api import async_playwright

    results = {"updated": 0, "failed": 0, "no_content": 0}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=list(CHROMIUM_CONTAINER_ARGS))
        sem = asyncio.Semaphore(2)
        try:
            async def worker(oid: str, url: str) -> None:
                await process(oid, url, dry_run, browser, results, sem)
                done = sum(results.values())
                if done % 10 == 0:
                    print(f"  progreso {done}/{len(targets)}: {results}", flush=True)

            await asyncio.gather(*(worker(oid, url) for oid, url in targets))
        finally:
            await browser.close()
    print("RESULTADO:", results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquecer resumenes desde la fuente oficial")
    parser.add_argument("--limit", type=int, default=0, help="Maximo de filas (0 = todas)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.dry_run))
    sys.exit(0)


if __name__ == "__main__":
    main()
