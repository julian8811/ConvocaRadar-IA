"""Opcion B — operational priority layer (TDD).

Large reports (> 12 items) must prioritize: sticky priority bar with counts,
urgent closings as cards first, the rest in a dense 1-row-per-item table,
and the unvalidated backlog collapsed. Small reports keep the legacy
full-card layout (structural compat) and only gain the priority bar.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.export import generate_report_html


def _opp(title, status="open", days=None, **kw):
    close = None
    if days is not None:
        close = datetime.now() + timedelta(days=days)  # naive; compared at date level
    base = dict(
        source_id="src-1",
        status=status,
        country="Colombia",
        title=title,
        entity="Test Entity",
        summary="Summary",
        description="",
        close_date=close,
        funding_amount_raw="",
        funding_amount_value=None,
        categories=[],
        official_url="",
        application_url=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _big(n=15):
    # NOTE: titles carry "-" (outside the base64 alphabet) so find() can't
    # match the embedded logo bytes in <head>.
    opps = [_opp("U-urgent-%d" % i, days=3) for i in range(3)]
    opps += [_opp("R-rest-%d" % i, days=60) for i in range(n - 5)]
    opps += [_opp("X-backlog-%d" % i, status="unknown") for i in range(2)]
    return opps


class TestOperationalLayer:
    def test_small_reports_keep_full_cards_and_gain_priority_bar(self):
        html = generate_report_html("R", SimpleNamespace(name="Org"), [_opp("A"), _opp("B")])
        assert "Todas las convocatorias" in html
        assert "story-grid" in html
        assert "op-bar" in html  # priority bar is always present

    def test_large_reports_prioritize_urgent_with_dense_table(self):
        html = generate_report_html("R", SimpleNamespace(name="Org"), _big())
        assert "op-bar" in html
        assert "Por cerrar" in html
        assert "dense-table" in html
        assert "<details" in html
        assert html.find("U-urgent-0") < html.find("R-rest-0")  # urgent cards before dense rows

    def test_large_unsectorized_has_no_grouping_markup(self):
        html = generate_report_html("R", SimpleNamespace(name="Org"), _big())
        assert "sector-group" not in html

    def test_no_external_fonts_or_network(self):
        html = generate_report_html("R", SimpleNamespace(name="Org"), _big())
        assert "fonts.googleapis.com" not in html
