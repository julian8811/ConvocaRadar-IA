"""Export utilities: CSV, XLSX, PDF, HTML report generation.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime
from html import escape

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

_BRAND_PRIMARY = "#005652"
_BRAND_SECONDARY = "#00b3af"
_BRAND_ACCENT = "#00807d"
_BRAND_DARK = "#003432"
_BRAND_GOLD = "#ffcd00"
_BRAND_BG = "#f4f9f8"

_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="56" height="56">'
    '<rect width="200" height="200" rx="36" fill="#005652"/>'
    '<path d="M58 72 L100 48 L142 72 L142 108 C142 138 100 162 100 162 C100 162 58 138 58 108Z" '
    'fill="none" stroke="#00b3af" stroke-width="6"/>'
    '<path d="M82 95 C82 88 88 82 95 82 L105 82 C112 82 118 88 118 95 L118 105 '
    'C118 112 112 118 105 118 L95 118 C88 118 82 112 82 105Z" fill="#ffcd00"/>'
    '<circle cx="100" cy="100" r="6" fill="#003432"/>'
    '<text x="100" y="148" text-anchor="middle" fill="#00b3af" font-family="Arial,sans-serif" '
    'font-size="16" font-weight="bold">CR</text>'
    '</svg>'
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
        return "No disponible"

    def _link_for(item: Opportunity) -> str:
        return item.official_url or item.application_url or "#"

    from app.services.validation import url_is_reachable  # lazy: avoid heavy import at module level

    featured = opportunities[:9]
    featured_cards = "\n".join(
        f"""
        <article class="story-card">
          <div class="story-card__top">
            <span class="badge badge--{escape(item.status)}">{escape(item.status.replace('_', ' '))}</span>
            <span class="story-card__country">{escape(item.country)}</span>
          </div>
          <h3 class="story-card__title">{f'<a href="{escape(_link_for(item))}" target="_blank" rel="noopener noreferrer">{escape(repair_mojibake(item.title))}</a>' if _link_for(item) != '#' else escape(repair_mojibake(item.title))}</h3>
          <p class="story-card__body">{escape(repair_mojibake(item.summary or item.description or 'Sin resumen disponible.'))}</p>
          <div class="story-card__meta-grid">
            <div class="story-card__metaitem">
              <span class="story-card__label">Entidad</span>
              <span class="story-card__value">{escape(repair_mojibake(item.entity))}</span>
            </div>
            <div class="story-card__metaitem">
              <span class="story-card__label">Cierre</span>
              <span class="story-card__value">{escape(item.close_date.date().isoformat() if item.close_date else 'Sin fecha')}</span>
            </div>
            <div class="story-card__metaitem">
              <span class="story-card__label">Monto</span>
              <span class="story-card__value">{escape(_format_amount(item))}</span>
            </div>
          </div>
          <div class="story-card__actions">
            {f'<a class="btn" href="{escape(_link_for(item))}" target="_blank" rel="noopener noreferrer">Ver convocatoria</a>' if _link_for(item) != '#' else ''}
            {f'<a class="btn btn--outline" href="{escape(item.application_url)}" target="_blank" rel="noopener noreferrer">Postular</a>' if item.application_url and url_is_reachable(item.application_url) else ''}
          </div>
        </article>
        """
        for item in featured
    )
    rows = "\n".join(
        f"""
        <tr>
          <td class="col-title">
            <a href="{escape(_link_for(o))}" target="_blank" rel="noopener noreferrer">{escape(repair_mojibake(o.title))}</a>
            <span>{escape(repair_mojibake((o.summary or o.description or 'Sin resumen disponible.')[:140]))}</span>
          </td>
          <td>{escape(repair_mojibake(o.entity))}</td>
          <td>{escape(o.country)}</td>
          <td><span class="badge badge--{escape(o.status)}">{escape(o.status.replace('_', ' '))}</span></td>
          <td>{escape(o.close_date.date().isoformat() if o.close_date else 'Sin fecha')}</td>
          <td>{escape(_format_amount(o))}</td>
        </tr>
        """
        for o in opportunities
    )
    country_rows = "\n".join(f"<tr><td>{escape(country)}</td><td>{count}</td></tr>" for country, count in top_countries)
    category_rows = "\n".join(f"<tr><td>{escape(category)}</td><td>{count}</td></tr>" for category, count in top_categories)
    return f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>{escape(title)}</title>
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
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 32px 18px 48px;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
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
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px;
}}
.story-card {{
  border: 1px solid var(--border); border-radius: 18px;
  background: var(--surface);
  padding: 20px; display: flex; flex-direction: column;
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
  margin: 0 0 8px; font-size: 1.05rem; line-height: 1.3; color: var(--dark);
}}
.story-card__title a:hover {{ color: var(--primary); }}
.story-card__body {{
  margin: 0; color: var(--muted); font-size: 0.88rem;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
  overflow: hidden; flex: 1;
}}
.story-card__meta-grid {{
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
  margin: 14px 0 0; padding-top: 14px;
  border-top: 1px solid rgba(0,86,82,0.08);
}}
.story-card__metaitem {{
  display: flex; flex-direction: column; gap: 2px;
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
@media (max-width: 1100px) {{
  .story-grid {{ grid-template-columns: 1fr 1fr; }}
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
  <div class="brand-logo">{_LOGO_SVG}</div>
  <div class="brand-text">
    <div class="brand-name">ConvocaRadar IA</div>
    <div class="brand-tagline">Observatorio Inteligente de Convocatorias &middot; {escape(org_name)}</div>
  </div>
</div>

<section class="hero">
  <div class="hero__inner">
    <h1>{escape(title)}</h1>
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
    <p class="section__subtitle">Listado completo con enlace oficial a cada convocatoria.</p>
  </div>
  <div class="section__body grid-table-wrap">
    <table>
      <thead><tr><th>T&iacute;tulo</th><th>Entidad</th><th>Pa&iacute;s</th><th>Estado</th><th>Cierre</th><th>Monto</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="6">Sin convocatorias disponibles</td></tr>'}</tbody>
    </table>
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
                Paragraph(escape(repair_mojibake(item.title)), styles["BodyText"]),
                Paragraph(escape(repair_mojibake(item.entity)), styles["BodyText"]),
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
