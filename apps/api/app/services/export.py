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


def generate_report_html(title: str, organization: object, opportunities: list[Opportunity]) -> str:
    """Generate a rich HTML report for an organization's opportunities.

    The ``organization`` argument is duck-typed: it must have a ``name`` attribute.
    """
    org_name = getattr(organization, "name", "Organización")
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
          <div class="story-card__header">
            <span class="story-card__eyebrow">{escape(item.status.replace('_', ' '))}</span>
            <span class="story-card__meta">{escape(item.country)}</span>
          </div>
          <h3 class="story-card__title">{f'<a href="{escape(_link_for(item))}" target="_blank" rel="noopener noreferrer">{escape(item.title)}</a>' if _link_for(item) != '#' else escape(item.title)}</h3>
          <p class="story-card__body">{escape(item.summary or item.description or 'Sin resumen disponible.')}</p>
          <dl class="story-card__facts">
            <div><dt>Entidad</dt><dd>{escape(item.entity)}</dd></div>
            <div><dt>Cierre</dt><dd>{escape(item.close_date.date().isoformat() if item.close_date else 'Sin fecha')}</dd></div>
            <div><dt>Monto</dt><dd>{escape(_format_amount(item))}</dd></div>
            <div><dt>Fuente</dt><dd>{escape(item.source_id or 'Sin fuente')}</dd></div>
          </dl>
          <div class="story-card__actions">
            {f'<a class="link-button" href="{escape(_link_for(item))}" target="_blank" rel="noopener noreferrer">Ver convocatoria</a>' if _link_for(item) != '#' else ''}
            {f'<a class="link-button link-button--ghost" href="{escape(item.application_url)}" target="_blank" rel="noopener noreferrer">Postular</a>' if item.application_url and url_is_reachable(item.application_url) else ''}
          </div>
        </article>
        """
        for item in featured
    )
    rows = "\n".join(
        f"""
        <tr>
          <td class="col-title">
            <a href="{escape(_link_for(o))}" target="_blank" rel="noopener noreferrer">{escape(o.title)}</a>
            <span>{escape((o.summary or o.description or 'Sin resumen disponible.')[:140])}</span>
          </td>
          <td>{escape(o.entity)}</td>
          <td>{escape(o.country)}</td>
          <td><span class="status status--{escape(o.status)}">{escape(o.status)}</span></td>
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
  --bg: #f8fafc;
  --surface: rgba(255,255,255,0.92);
  --surface-strong: #ffffff;
  --text: #0f172a;
  --muted: #52617a;
  --border: #d8e1f3;
  --accent: #0d4e5e;
  --accent-soft: rgba(13, 78, 94, 0.09);
  --accent-2: #4f46e5;
  --success: #15803d;
  --warning: #b45309;
  --danger: #b91c1c;
  --shadow: 0 18px 42px -18px rgba(15, 23, 42, 0.24);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 32px 18px 48px;
  font-family: Inter, Arial, sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top, rgba(13, 78, 94, 0.1), transparent 34%),
    linear-gradient(180deg, #faf8ff 0%, #eef2ff 100%);
  line-height: 1.5;
}}
a {{ color: inherit; text-decoration: none; }}
.shell {{ max-width: 1240px; margin: 0 auto; }}
.hero {{
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(242,243,255,0.92));
  box-shadow: var(--shadow);
  padding: 28px;
}}
.hero::after {{
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at top right, rgba(79, 70, 229, 0.12), transparent 28%),
    radial-gradient(circle at bottom left, rgba(13, 78, 94, 0.12), transparent 24%);
  pointer-events: none;
}}
.hero__inner {{ position: relative; z-index: 1; display: grid; gap: 18px; }}
.eyebrow {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(13, 78, 94, 0.16);
  background: rgba(13, 78, 94, 0.06);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
h1 {{
  margin: 0;
  font-size: clamp(2rem, 4vw, 3.5rem);
  line-height: 1.03;
  letter-spacing: -0.03em;
  font-family: "Space Grotesk", "Inter", Arial, sans-serif;
}}
.hero__lead {{
  max-width: 720px;
  font-size: 1.06rem;
  color: var(--muted);
  margin: 0;
}}
.hero__toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px; }}
.button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  padding: 0 16px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface-strong);
  color: var(--text);
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}}
.button--primary {{ border-color: transparent; background: linear-gradient(135deg, var(--accent), #0f766e); color: #fff; }}
.button--ghost {{ background: rgba(255,255,255,0.8); }}
.grid-stats {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 32px;
}}
.stat {{
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px;
  background: var(--surface);
}}
.stat span {{
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}}
.stat strong {{ display: block; margin-top: 6px; font-size: 28px; line-height: 1; color: var(--text); }}
.section {{
  margin-top: 26px;
  border: 1px solid var(--border);
  border-radius: 22px;
  background: var(--surface);
  box-shadow: 0 10px 28px -18px rgba(15, 23, 42, 0.22);
  overflow: hidden;
}}
.section__head {{ padding: 20px 22px 0; }}
.section__title {{ margin: 0; font-family: "Space Grotesk", "Inter", Arial, sans-serif; font-size: 1.35rem; }}
.section__subtitle {{ margin: 6px 0 0; color: var(--muted); font-size: 0.96rem; }}
.section__body {{ padding: 20px 22px 24px; }}
.grid-2 {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.story-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
.story-card {{
  border: 1px solid var(--border);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(248,250,252,0.98));
  padding: 18px;
  min-height: 100%;
}}
.story-card__header {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }}
.story-card__eyebrow {{
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}}
.story-card__meta {{ color: var(--muted); font-size: 12px; }}
.story-card__title {{ margin: 0 0 10px; font-size: 1.12rem; line-height: 1.3; }}
.story-card__title a:hover {{ color: var(--accent); }}
.story-card__body {{ margin: 0; color: var(--muted); font-size: 0.96rem; }}
.story-card__facts {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  margin: 16px 0 0;
}}
.story-card__facts div {{ padding-top: 10px; border-top: 1px solid rgba(82, 97, 122, 0.15); }}
.story-card__facts dt {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }}
.story-card__facts dd {{ margin: 4px 0 0; font-size: 0.93rem; font-weight: 600; color: var(--text); }}
.story-card__actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }}
.link-button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border-radius: 11px;
  background: var(--accent);
  color: #fff;
  font-size: 0.88rem;
  font-weight: 700;
}}
.link-button--ghost {{
  background: rgba(79, 70, 229, 0.09);
  color: var(--accent-2);
  border: 1px solid rgba(79, 70, 229, 0.18);
}}
table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
thead th {{
  background: #f2f5fb;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border-bottom: 1px solid var(--border);
  text-align: left;
  padding: 12px 14px;
}}
tbody td {{ border-bottom: 1px solid rgba(216, 225, 243, 0.9); padding: 13px 14px; font-size: 13px; vertical-align: top; }}
tbody tr:hover {{ background: rgba(13, 78, 94, 0.03); }}
.col-title a {{ display: block; font-weight: 700; color: var(--text); }}
.col-title span {{ display: block; margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.35; }}
.status {{
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-transform: capitalize;
}}
.status--open {{ background: rgba(21, 128, 61, 0.1); color: var(--success); }}
.status--closing_soon {{ background: rgba(180, 83, 9, 0.1); color: var(--warning); }}
.status--closed {{ background: rgba(100, 116, 139, 0.12); color: #475569; }}
.status--unknown {{ background: rgba(100, 116, 139, 0.12); color: #475569; }}
.status--draft {{ background: rgba(79, 70, 229, 0.1); color: var(--accent-2); }}
.status--archived {{ background: rgba(100, 116, 139, 0.12); color: #475569; }}
.note {{ font-size: 12px; color: var(--muted); margin: 0; }}
.stack {{ display: grid; gap: 18px; }}
.grid-table-wrap {{ overflow-x: auto; }}
@media (max-width: 1100px) {{
  .grid-stats, .story-grid, .grid-2 {{ grid-template-columns: 1fr 1fr; }}
}}
@media (max-width: 760px) {{
  body {{ padding: 18px 12px 28px; }}
  .hero, .section {{ border-radius: 18px; }}
  .grid-stats, .story-grid, .grid-2 {{ grid-template-columns: 1fr; }}
  .story-card__facts {{ grid-template-columns: 1fr; }}
}}
</style></head>
<body>
<div class="shell">
<section class="hero">
  <div class="hero__inner">
    <div class="eyebrow">ConvocaRadar IA</div>
    <h1>{escape(title)}</h1>
    <p class="hero__lead">Organización: {escape(org_name)} · Generado: {datetime.now(UTC).date().isoformat()} · Reporte ejecutivo de oportunidades filtradas y priorizadas para revisión institucional.</p>
    <div class="hero__toolbar">
      <a class="button button--primary" href="#oportunidades">Ver convocatorias</a>
      <a class="button" href="#resumen">Resumen ejecutivo</a>
      <a class="button button--ghost" href="#metodologia">Metodología</a>
    </div>
  </div>
</section>

<section class="grid-stats" aria-label="Resumen de indicadores">
  <div class="stat"><span>Total oportunidades</span><strong>{total}</strong></div>
  <div class="stat"><span>Abiertas</span><strong>{open_count}</strong></div>
  <div class="stat"><span>Por cerrar</span><strong>{closing_soon_count}</strong></div>
  <div class="stat"><span>Con fecha de cierre</span><strong>{with_date}</strong></div>
  <div class="stat"><span>Con fuente</span><strong>{with_source}</strong></div>
  <div class="stat"><span>Con resumen</span><strong>{with_summary}</strong></div>
  <div class="stat"><span>Con monto</span><strong>{with_amount}</strong></div>
  <div class="stat"><span>Sin validar</span><strong>{unknown_count}</strong></div>
</section>

<section class="section" id="resumen">
  <div class="section__head">
    <h2 class="section__title">Resumen ejecutivo</h2>
    <p class="section__subtitle">Lectura rápida del estado de la cartera de convocatorias.</p>
  </div>
  <div class="section__body stack">
    <p>Se identificaron {total} oportunidades relevantes para revisión institucional. {closed_count} ya están cerradas y {closing_soon_count} requieren atención cercana.</p>
    <div class="grid-2">
      <div>
        <table><thead><tr><th>Principales países</th><th>Oportunidades</th></tr></thead><tbody>{country_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
      </div>
      <div>
        <table><thead><tr><th>Principales categorías</th><th>Oportunidades</th></tr></thead><tbody>{category_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
      </div>
    </div>
  </div>
</section>

<section class="section">
  <div class="section__head">
    <h2 class="section__title">Panorama visual</h2>
    <p class="section__subtitle">Bloques editoriales para revisar la cartera con más contexto.</p>
  </div>
  <div class="section__body">
    <div class="story-grid">
      {featured_cards or '<div class="story-card"><p class="story-card__body">No hay convocatorias para mostrar.</p></div>'}
    </div>
  </div>
</section>

<section class="section" id="oportunidades">
  <div class="section__head">
    <h2 class="section__title">Convocatorias recomendadas</h2>
    <p class="section__subtitle">Cada título enlaza la convocatoria oficial para consultar y actuar directamente.</p>
  </div>
  <div class="section__body grid-table-wrap">
    <table>
      <thead><tr><th>Título</th><th>Entidad</th><th>País</th><th>Estado</th><th>Cierre</th><th>Monto</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="6">Sin convocatorias disponibles</td></tr>'}</tbody>
    </table>
  </div>
</section>

<section class="section" id="metodologia">
  <div class="section__head">
    <h2 class="section__title">Metodología</h2>
    <p class="section__subtitle">Formato listo para lectura ejecutiva, exportación e impresión.</p>
  </div>
  <div class="section__body stack">
    <p>Reporte generado desde fuentes configuradas, con normalización, deduplicación y priorización automática. El archivo PDF se renderiza con Playwright y, si el motor no está disponible, cae a una salida tipográfica de respaldo.</p>
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
    org_name = getattr(organization, "name", "Organización")
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
        Paragraph(f"Generado: {datetime.now(UTC).date().isoformat()}", styles["Normal"]),
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
                Paragraph(escape(item.title), styles["BodyText"]),
                Paragraph(escape(item.entity), styles["BodyText"]),
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
