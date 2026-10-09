"""T3 (runall-abort): the Modest backend (selectolax.parser.HTMLParser) is
dead — production scrapes fail. All connectors + dom_monitor must use
selectolax.lexbor.LexborHTMLParser (aliased as HTMLParser to minimize diff).

RED on the old code: connector modules still import selectolax.parser.
GREEN: zero selectolax.parser imports under app/connectors + dom_monitor,
with css/text/attributes parity on a representative fixture.
"""

from __future__ import annotations

import pathlib


CONNECTORS_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "connectors"
DOM_MONITOR = (
    pathlib.Path(__file__).resolve().parent.parent / "app" / "scraper" / "dom_monitor.py"
)


def _parser_imports(path: pathlib.Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if "selectolax.parser import" in line
    ]


def test_no_modest_parser_imports_in_connectors() -> None:
    offenders = {
        str(p.name): _parser_imports(p)
        for p in sorted(CONNECTORS_DIR.glob("*.py"))
        if _parser_imports(p)
    }
    assert offenders == {}, (
        f"Modest backend still imported (use selectolax.lexbor instead): {offenders}"
    )


def test_no_modest_parser_import_in_dom_monitor() -> None:
    assert _parser_imports(DOM_MONITOR) == [], (
        f"dom_monitor still imports Modest backend: {_parser_imports(DOM_MONITOR)}"
    )


def test_lexbor_css_text_attributes_parity() -> None:
    """The connector API surface (css/css_first/text/attributes/html) must
    behave on a representative card-list fixture."""
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    html = (
        "<html><body>"
        '<div class="card"><h2>Beca Innovación</h2>'
        '<a href="/convocatorias/beca-2025" title="Postular">Ver más</a>'
        "<p>Cierra: 2025-06-30</p></div>"
        '<div class="card"><h2>Otra</h2></div>'
        "</body></html>"
    )
    tree = HTMLParser(html)
    cards = tree.css("div.card")
    assert len(cards) == 2
    anchor = tree.css_first("div.card a")
    assert anchor is not None
    assert anchor.attributes.get("href") == "/convocatorias/beca-2025"
    assert anchor.attributes.get("title") == "Postular"
    assert "Beca" in cards[0].text(deep=True, separator=" ", strip=True)
    assert "Cierra" in tree.css_first("div.card p").text()
    assert "card" in cards[0].html
