"""Exportar los informes de convocatorias de la base a PDF.

Renderiza el mismo HTML del informe con Chromium (Playwright), conservando
la linea grafica (colores, tipografia Geist, tarjetas) y dejando los enlaces
de cada convocatoria como anotaciones clickeables en el PDF.

Usage:
    python scripts/export_reports_pdf.py --out /ruta/destino [--mes Agosto]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from app.db.session import SessionLocal


def slug_mes(title: str) -> str:
    mes = title.split("\u2014")[-1].strip()
    return f"Informe convocatorias - {mes}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Exportar informes HTML a PDF")
    parser.add_argument("--out", required=True, help="Carpeta destino de los PDF")
    parser.add_argument("--mes", default=None, help="Filtrar por mes (substring del titulo)")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(args.out, exist_ok=True)

    with SessionLocal() as db:
        rows = db.execute(
            text("SELECT title, html_content FROM reports ORDER BY generated_at")
        ).all()
    if args.mes:
        rows = [r for r in rows if args.mes.lower() in r[0].lower()]

    print(f"informes a exportar: {len(rows)}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for title, html in rows:
                out_path = os.path.join(args.out, f"{slug_mes(title)}.pdf")
                page = browser.new_page()
                try:
                    page.emulate_media(media="print")
                    page.set_content(html, wait_until="networkidle", timeout=45000)
                except Exception:
                    # Si la red de fuentes demora, seguir con lo cargado.
                    pass
                page.wait_for_timeout(1200)  # asentar fuentes web
                page.pdf(
                    path=out_path,
                    format="A4",
                    print_background=True,
                    margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
                    display_header_footer=False,
                )
                size_kb = os.path.getsize(out_path) // 1024
                print(f"OK {out_path} ({size_kb} KB)")
                page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
