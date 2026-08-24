"""Export utilities: CSV, XLSX, PDF, HTML report generation.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime

from app.core.text import safe_escape

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Opportunity, OpportunityStatus
from app.core.time import format_bogota, now_bogota
from app.core.text import repair_mojibake


def export_csv(opportunities: list[Opportunity]) -> str:
    """Export opportunities as CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "entity", "country", "status", "close_date", "funding_amount", "official_url"])
    for item in opportunities:
        writer.writerow([
            item.title,
            item.entity,
            item.country,
            item.status,
            item.close_date.date().isoformat() if item.close_date else "",
            item.funding_amount_raw or item.funding_amount_value or "",
            item.official_url or "",
        ])
    return output.getvalue()


def export_xlsx(opportunities: list[Opportunity]) -> bytes:
    """Export opportunities as XLSX bytes."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Convocatorias"
    sheet.append(["Titulo", "Entidad", "Pais", "Estado", "Cierre", "Monto", "URL oficial"])
    for item in opportunities:
        sheet.append(
            [
                item.title,
                item.entity,
                item.country,
                item.status,
                item.close_date.date().isoformat() if item.close_date else "",
                item.funding_amount_raw or item.funding_amount_value or "",
                item.official_url or "",
            ]
        )
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 48)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


# ── Institutional brand constants ──────────────────────────────────────────

_BRAND_PRIMARY = "#00807d"
_BRAND_SECONDARY = "#00b3af"
_BRAND_ACCENT = "#006562"
_BRAND_DARK = "#2c3339"
_BRAND_GOLD = "#f39a1a"
_BRAND_BG = "#f6faff"
_BRAND_FONT = '"Geist", system-ui, -apple-system, sans-serif'

_LOGO_B64 = "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"

_LOGO_IMG = (
    f'<img src="data:image/png;base64,{_LOGO_B64}" '
    f'alt="Observatorio de Convocatorias Institucional" '
    f'style="height:48px;width:auto;object-fit:contain;" />'
)


def generate_report_html(title: str, organization: object, opportunities: list[Opportunity]) -> str:
    """Generate a rich HTML report for an organization's opportunities.

    The ``organization`` argument is duck-typed: it must have a ``name`` attribute.
    """
    org_name = repair_mojibake(getattr(organization, "name", "Organización"))
    total = len(opportunities)
    open_count = sum(1 for item in opportunities if item.status == OpportunityStatus.open.value)
    closing_soon_count = sum(1 for item in opportunities if item.status == OpportunityStatus.closing_soon.value)
    closed_count = sum(1 for item in opportunities if item.status == OpportunityStatus.closed.value)
    unknown_count = sum(1 for item in opportunities if item.status == OpportunityStatus.unknown.value)
    with_source = sum(1 for item in opportunities if item.source_id)
    with_summary = sum(1 for item in opportunities if item.summary.strip())
    with_amount = sum(1 for item in opportunities if item.funding_amount_raw or item.funding_amount_value)
    with_date = sum(1 for item in opportunities if item.close_date)
    countries = sorted({item.country for item in opportunities if item.country})
    categories = sorted({category for item in opportunities for category in item.categories if category})
    top_countries = sorted(
        ((country, sum(1 for item in opportunities if item.country == country)) for country in countries),
        key=lambda entry: (-entry[1], entry[0]),
    )[:6]
    top_categories = sorted(
        ((category, sum(1 for item in opportunities if category in item.categories)) for category in categories),
        key=lambda entry: (-entry[1], entry[0]),
    )[:6]

    def _format_amount(item: Opportunity) -> str:
        if item.funding_amount_raw:
            return item.funding_amount_raw
        if item.funding_amount_value is not None:
            return f"{item.funding_amount_value:,.0f}".replace(",", ".")
        return ""

    def _link_for(item: Opportunity) -> str:
        return item.official_url or item.application_url or "#"

    from app.services.validation import url_is_reachable  # lazy: avoid heavy import at module level

    def _rich_summary(item: Opportunity) -> str:
        """Return the best available summary, filtering noise."""
        text = (item.summary or item.description or '').strip()
        if not text:
            return ''
        # Filter sitemap noise (with or without colon)
        if text.lower().startswith('sitemap entry'):
            return ''
        # Filter sitemap noise from connectors
        slug_prefixes = ('convocatoria uniandes:', 'findeter ')
        if any(text.lower().startswith(p) for p in slug_prefixes):
            return ''
        # Filter grant ID patterns like "DFOP0018586 | DOS-SA | Status: posted"
        import re as _re
        if _re.match(r'^[A-Z0-9\-]+\s*\|\s*[A-Z0-9\-]+\s*\|\s*Status:\s*', text):
            return ''
        # Filter lines starting with "Title " (UNDP RFP titles)
        if text.startswith('Title '):
            return ''
        # Filter URLs
        if text.startswith('http'):
            return ''
        return text

    def _card_html(item: Opportunity) -> str:
        body_text = _rich_summary(item)
        has_summary = bool(body_text)
        has_close = bool(item.close_date)
        has_amount = bool(item.funding_amount_raw or item.funding_amount_value)
        has_categories = bool(item.categories)
        entity_str = safe_escape(repair_mojibake(item.entity or ''))
        # Extract domain from URL as fallback context
        domain_str = ''
        url = _link_for(item)
        if url and url != '#':
            try:
                from urllib.parse import urlparse as _up
                domain_str = _up(url).netloc.replace('www.', '')
            except Exception:
                pass
        # Build category chips
        chips = ''
        if has_categories:
            chips = ' <div class="story-card__chips">' + ''.join(
                f'<span class="chip">{safe_escape(cat)}</span>'
                for cat in item.categories[:4]
            ) + '</div>'
        # Show domain when both entity and summary are generic
        show_domain = (not has_summary) and domain_str and (not entity_str or entity_str in ('Findeter', 'Universidad de los Andes'))
        return f"""
        <article class="story-card{' story-card--compact' if not has_summary else ''}">
          <div class="story-card__top">
            <span class="badge badge--{safe_escape(item.status)}">{safe_escape(item.status.replace('_', ' '))}</span>
            <span class="story-card__country">{safe_escape(item.country or '')}</span>
          </div>
          <h3 class="story-card__title">{f'<a href="{safe_escape(url)}" target="_blank" rel="noopener noreferrer">{safe_escape(repair_mojibake(item.title))}</a>' if url != '#' else safe_escape(repair_mojibake(item.title))}</h3>
          {f'<p class="story-card__body">{safe_escape(repair_mojibake(body_text))}</p>' if has_summary else ''}
          {chips}
          <div class="story-card__meta-grid">
            <div class="story-card__metaitem" title="{entity_str}">
              <span class="story-card__label">{'Fuente' if show_domain else 'Entidad'}</span>
              <span class="story-card__value">{entity_str if not show_domain else domain_str}</span>
            </div>
            <div class="story-card__metaitem">
              <span class="story-card__label">Cierre</span>
              <span class="story-card__value">{safe_escape(item.close_date.date().isoformat() if has_close else '—')}</span>
            </div>
            <div class="story-card__metaitem">
              <span class="story-card__label">Monto</span>
              <span class="story-card__value">{safe_escape(_format_amount(item)) if has_amount else '—'}</span>
            </div>
          </div>
          <div class="story-card__actions">
            {f'<a class="btn" href="{safe_escape(url)}" target="_blank" rel="noopener noreferrer">Ver convocatoria</a>' if url != '#' else ''}
            {f'<a class="btn btn--outline" href="{safe_escape(item.application_url)}" target="_blank" rel="noopener noreferrer">Postular</a>' if item.application_url and url_is_reachable(item.application_url) else ''}
          </div>
        </article>
        """

    featured = opportunities[:9]
    featured_cards = "\n".join(_card_html(item) for item in featured)
    all_cards = "\n".join(_card_html(item) for item in opportunities)
    country_rows = "\n".join(f"<tr><td>{safe_escape(country)}</td><td>{count}</td></tr>" for country, count in top_countries)
    category_rows = "\n".join(f"<tr><td>{safe_escape(category)}</td><td>{count}</td></tr>" for category, count in top_categories)
    return f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>{safe_escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&display=swap" rel="stylesheet">
<style>
:root {{
  --primary: {_BRAND_PRIMARY};
  --secondary: {_BRAND_SECONDARY};
  --accent: {_BRAND_ACCENT};
  --dark: {_BRAND_DARK};
  --gold: {_BRAND_GOLD};
  --bg: {_BRAND_BG};
  --surface: #ffffff;
  --text: #0f172a;
  --muted: #52617a;
  --border: #d8e1f3;
  --success: #15803d;
  --warning: #b45309;
  --danger: #b91c1c;
  --shadow: 0 20px 48px -20px rgba(0,86,82,0.18);
  --brand-font: 'Libre Franklin', 'Inter', system-ui, -apple-system, sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 32px 18px 48px;
  font-family: var(--brand-font);
  color: var(--text);
  background: linear-gradient(180deg, {_BRAND_BG} 0%, #ffffff 100%);
  line-height: 1.5;
}}
a {{ color: inherit; text-decoration: none; }}
.shell {{ max-width: 1240px; margin: 0 auto; }}

/* ── Header / Brand bar ────────────────────────────────── */
.brand-bar {{
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 24px; padding: 16px 24px;
  background: var(--surface);
  border-radius: 20px; border: 1px solid var(--border);
  box-shadow: 0 4px 16px rgba(0,86,82,0.06);
}}
.brand-logo {{
  width: 52px; height: 52px; flex-shrink: 0;
}}
.brand-logo svg {{ width: 100%; height: 100%; }}
.brand-text {{
  flex: 1; display: flex; flex-direction: column; gap: 2px;
}}
.brand-name {{
  font-size: 1.2rem; font-weight: 700; color: var(--dark);
  letter-spacing: -0.02em;
}}
.brand-tagline {{
  font-size: 0.82rem; color: var(--muted);
}}

/* ── Hero ────────────────────────────────────────────────── */
.hero {{
  position: relative; overflow: hidden;
  border: 1px solid var(--border); border-radius: 24px;
  background: linear-gradient(135deg, var(--surface), rgba(0,179,175,0.04));
  box-shadow: var(--shadow); padding: 32px;
}}
.hero::after {{
  content: ""; position: absolute; inset: 0;
  background:
    radial-gradient(circle at top right, rgba(0,179,175,0.08), transparent 28%),
    radial-gradient(circle at bottom left, rgba(0,86,82,0.06), transparent 24%);
  pointer-events: none;
}}
.hero__inner {{ position: relative; z-index: 1; }}
h1 {{
  margin: 0; font-size: clamp(1.8rem, 3.5vw, 3rem);
  line-height: 1.05; letter-spacing: -0.025em;
  color: var(--dark);
}}
.hero__lead {{
  max-width: 700px; font-size: 1rem; color: var(--muted); margin: 12px 0 0;
}}
.hero__toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }}
.btn {{
  display: inline-flex; align-items: center; justify-content: center;
  min-height: 40px; padding: 0 18px; border-radius: 12px;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--text); font-weight: 600; font-size: 0.9rem;
  transition: all 0.15s ease;
}}
.btn:hover {{ box-shadow: 0 4px 12px rgba(0,86,82,0.12); }}
.btn--primary {{
  border-color: transparent; background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
}}
.btn--outline {{
  border-color: var(--secondary); color: var(--primary);
  background: transparent;
}}

/* ── Stats grid ──────────────────────────────────────────── */
.stats-grid {{
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  margin: 24px 0 32px;
}}
.stat {{
  border: 1px solid var(--border); border-radius: 18px; padding: 16px;
  background: var(--surface); box-shadow: 0 2px 8px rgba(0,86,82,0.04);
}}
.stat:hover {{ border-color: var(--secondary); }}
.stat span {{
  display: block; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted);
}}
.stat strong {{
  display: block; margin-top: 6px; font-size: 28px; line-height: 1;
  color: var(--dark);
}}

/* ── Sections ─────────────────────────────────────────────── */
.section {{
  margin-top: 24px;
  border: 1px solid var(--border); border-radius: 22px;
  background: var(--surface); box-shadow: var(--shadow); overflow: hidden;
}}
.section__head {{ padding: 22px 24px 0; }}
.section__title {{ margin: 0; font-size: 1.25rem; color: var(--dark); }}
.section__subtitle {{ margin: 6px 0 0; color: var(--muted); font-size: 0.92rem; }}
.section__body {{ padding: 20px 24px 24px; }}

/* ── Story cards (improved) ───────────────────────────────── */
.story-grid {{
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
}}
.story-card {{
  border: 1px solid var(--border); border-radius: 18px;
  background: var(--surface);
  padding: 18px; display: flex; flex-direction: column;
  min-width: 0; word-wrap: break-word; overflow-wrap: break-word;
  transition: all 0.15s ease;
}}
.story-card:hover {{
  border-color: var(--secondary); box-shadow: 0 8px 24px rgba(0,179,175,0.1);
}}
.story-card__top {{
  display: flex; justify-content: space-between; align-items: center;
  gap: 10px; margin-bottom: 12px; flex-wrap: wrap;
}}
.story-card__country {{ color: var(--muted); font-size: 0.82rem; }}
.story-card__title {{
  margin: 0 0 8px; font-size: 0.95rem; line-height: 1.25; color: var(--dark);
  overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}}
.story-card__title a:hover {{ color: var(--primary); }}
.story-card__body {{
  margin: 0; color: var(--muted); font-size: 0.88rem;
  line-height: 1.45;
}}
.story-card__meta-grid {{
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;
  margin: 12px 0 0; padding-top: 10px;
  border-top: 1px solid rgba(0,86,82,0.08);
}}
.story-card__metaitem {{
  display: flex; flex-direction: column; gap: 2px;
  min-width: 0;
}}
.story-card__label {{
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
  font-weight: 700; color: var(--muted);
}}
.story-card__value {{
  font-size: 0.82rem; font-weight: 600; color: var(--dark);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.story-card__actions {{
  display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px;
}}

/* ── Chips (categories) ────────────────────────────────────── */
.story-card__chips {{
  display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0 0;
}}
.chip {{
  display: inline-block; padding: 2px 8px;
  border-radius: 999px; font-size: 0.7rem; font-weight: 600;
  background: rgba(0,128,125,0.08); color: var(--primary);
  letter-spacing: 0.02em;
}}

/* ── Compact card (no summary) ─────────────────────────────── */
.story-card--compact .story-card__meta-grid {{
  margin-top: 8px;
}}

/* ── Badges ───────────────────────────────────────────────── */
.badge {{
  display: inline-flex; align-items: center; padding: 4px 10px;
  border-radius: 999px; font-size: 0.75rem; font-weight: 700;
  text-transform: capitalize; letter-spacing: 0.02em;
}}
.badge--open {{ background: rgba(21,128,61,0.1); color: var(--success); }}
.badge--closing_soon {{ background: rgba(180,83,9,0.1); color: var(--warning); }}
.badge--closed {{ background: rgba(100,116,139,0.12); color: #475569; }}
.badge--unknown {{ background: rgba(100,116,139,0.12); color: #475569; }}
.badge--draft {{ background: rgba(0,179,175,0.1); color: var(--primary); }}
.badge--archived {{ background: rgba(100,116,139,0.12); color: #475569; }}

/* ── Table ─────────────────────────────────────────────────── */
.grid-table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; }}
thead th {{
  background: {_BRAND_BG}; color: var(--dark); font-size: 0.75rem;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 2px solid var(--secondary);
  text-align: left; padding: 12px 14px;
}}
tbody td {{
  border-bottom: 1px solid rgba(0,86,82,0.06); padding: 12px 14px;
  font-size: 0.85rem; vertical-align: top;
}}
tbody tr:hover {{ background: rgba(0,179,175,0.03); }}
.col-title a {{ display: block; font-weight: 700; color: var(--dark); }}
.col-title a:hover {{ color: var(--primary); }}
.col-title span {{ display: block; margin-top: 3px; color: var(--muted); font-size: 0.78rem; }}

/* ── Methodology ─────────────────────────────────────────── */
.stack {{ display: grid; gap: 14px; }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.note {{ font-size: 0.82rem; color: var(--muted); margin: 0; }}

/* ── Responsive ───────────────────────────────────────────── */
@media (max-width: 1400px) {{
  .story-grid {{ grid-template-columns: repeat(3, 1fr); }}
}}
@media (max-width: 1100px) {{
  .story-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
@media (max-width: 760px) {{
  body {{ padding: 18px 12px 28px; }}
  .brand-bar {{ flex-wrap: wrap; }}
  .story-grid, .stats-grid, .grid-2 {{ grid-template-columns: 1fr; }}
  .story-card__meta-grid {{ grid-template-columns: 1fr; }}
}}
</style></head>
<body>
<div class="shell">

<div class="brand-bar">
  <div class="brand-logo">{_LOGO_IMG}</div>
  <div class="brand-text">
    <div class="brand-name">Observatorio de Convocatorias</div>
    <div class="brand-tagline">{safe_escape(org_name)} &middot; Institución Universitaria Colmayor</div>
  </div>
</div>

<section class="hero">
  <div class="hero__inner">
    <h1>{safe_escape(title)}</h1>
    <p class="hero__lead">Generado: {format_bogota(now_bogota())} (hora de Bogot&aacute;) &middot; {total} oportunidades identificadas.</p>
    <div class="hero__toolbar">
      <a class="btn btn--primary" href="#oportunidades">Ver convocatorias</a>
      <a class="btn" href="#resumen">Resumen ejecutivo</a>
      <a class="btn" href="#metodologia">Metodolog&iacute;a</a>
    </div>
  </div>
</section>

<section class="stats-grid" aria-label="Indicadores">
  <div class="stat"><span>Total</span><strong>{total}</strong></div>
  <div class="stat"><span>Abiertas</span><strong>{open_count}</strong></div>
  <div class="stat"><span>Por cerrar</span><strong>{closing_soon_count}</strong></div>
  <div class="stat"><span>Con fecha</span><strong>{with_date}</strong></div>
  <div class="stat"><span>Con fuente</span><strong>{with_source}</strong></div>
  <div class="stat"><span>Con resumen</span><strong>{with_summary}</strong></div>
  <div class="stat"><span>Con monto</span><strong>{with_amount}</strong></div>
  <div class="stat"><span>Sin validar</span><strong>{unknown_count}</strong></div>
</section>

<section class="section" id="resumen">
  <div class="section__head">
    <h2 class="section__title">Resumen ejecutivo</h2>
    <p class="section__subtitle">Lectura r&aacute;pida del estado de la cartera de convocatorias.</p>
  </div>
  <div class="section__body stack">
    <p>Se identificaron {total} oportunidades relevantes. {closed_count} ya est&aacute;n cerradas y {closing_soon_count} requieren atenci&oacute;n inmediata.</p>
    <div class="grid-2">
      <div>
        <table><thead><tr><th>Pa&iacute;ses principales</th><th>Oportunidades</th></tr></thead><tbody>{country_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
      </div>
      <div>
        <table><thead><tr><th>Categor&iacute;as principales</th><th>Oportunidades</th></tr></thead><tbody>{category_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
      </div>
    </div>
  </div>
</section>

<section class="section">
  <div class="section__head">
    <h2 class="section__title">Convocatorias destacadas</h2>
    <p class="section__subtitle">Tarjetas editoriales con las oportunidades m&aacute;s relevantes.</p>
  </div>
  <div class="section__body">
    <div class="story-grid">
      {featured_cards or '<div class="story-card"><p class="story-card__body">No hay convocatorias para mostrar.</p></div>'}
    </div>
  </div>
</section>

<section class="section" id="oportunidades">
  <div class="section__head">
    <h2 class="section__title">Todas las convocatorias</h2>
    <p class="section__subtitle">{total} oportunidades identificadas en tarjetas con enlace oficial a cada convocatoria.</p>
  </div>
  <div class="section__body">
    <div class="story-grid">
      {all_cards or '<div class="story-card"><p class="story-card__body">No hay convocatorias disponibles.</p></div>'}
    </div>
  </div>
</section>

<section class="section" id="metodologia">
  <div class="section__head">
    <h2 class="section__title">Metodolog&iacute;a</h2>
    <p class="section__subtitle">Formato listo para lectura ejecutiva, exportaci&oacute;n e impresi&oacute;n.</p>
  </div>
  <div class="section__body stack">
    <p>Reporte generado desde +90 fuentes configuradas en 14 pa&iacute;ses, con normalizaci&oacute;n, deduplicaci&oacute;n y priorizaci&oacute;n autom&aacute;tica mediante algoritmos de compatibilidad y embeddings sem&aacute;nticos.</p>
    <p class="note">Cobertura de datos: {with_source} con fuente, {with_summary} con resumen, {with_amount} con monto y {with_date} con fecha de cierre.</p>
  </div>
</section>
</div>
</body></html>"""


async def _render_pdf_with_playwright(html: str) -> bytes:
    """Render HTML to PDF using Playwright."""
    from playwright.async_api import async_playwright

    from app.connectors.common import launch_chromium

    async with async_playwright() as playwright:
        browser = await launch_chromium(playwright)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1800})
            await page.set_content(html, wait_until="load")
            await page.emulate_media(media="print")
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "18mm", "right": "14mm", "bottom": "18mm", "left": "14mm"},
            )
        finally:
            await browser.close()


def export_pdf(title: str, organization: object, opportunities: list[Opportunity]) -> bytes:
    """Export opportunities as PDF bytes.

    Falls back to reportlab-based PDF if Playwright is unavailable.
    The ``organization`` argument is duck-typed: must have a ``name`` attribute.
    """
    org_name = repair_mojibake(getattr(organization, "name", "Organización"))
    html = generate_report_html(title, organization, opportunities)
    try:
        return asyncio.run(_render_pdf_with_playwright(html))
    except Exception:
        pass

    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, title=title, leftMargin=36, rightMargin=36)
    styles = getSampleStyleSheet()
    story: list[object] = [
        Paragraph(title, styles["Title"]),
        Paragraph(f"Organización: {org_name}", styles["Normal"]),
        Paragraph(f"Generado: {format_bogota(now_bogota())} (hora de Bogotá)", styles["Normal"]),
        Spacer(1, 16),
        Paragraph("Resumen ejecutivo", styles["Heading2"]),
        Paragraph(f"Se identificaron {len(opportunities)} oportunidades para revisión institucional.", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Convocatorias", styles["Heading2"]),
    ]
    data = [["Título", "Entidad", "País", "Estado", "Cierre", "Monto"]]
    for item in opportunities[:40]:
        data.append(
            [
                Paragraph(safe_escape(repair_mojibake(item.title)), styles["BodyText"]),
                Paragraph(safe_escape(repair_mojibake(item.entity)), styles["BodyText"]),
                item.country,
                item.status,
                item.close_date.date().isoformat() if item.close_date else "Sin fecha",
                item.funding_amount_raw or (str(item.funding_amount_value) if item.funding_amount_value is not None else "No disponible"),
            ]
        )
    table = Table(data, colWidths=[165, 120, 70, 60, 60, 85], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f3f5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.extend(
        [
            Spacer(1, 14),
            Paragraph("Metodología", styles["Heading2"]),
            Paragraph(
                "Reporte generado desde fuentes configuradas, con normalización, deduplicación y priorización automática.",
                styles["BodyText"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()
