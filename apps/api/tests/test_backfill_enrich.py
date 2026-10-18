"""T2c: backfill enrichment must skip news items and support --source-key.

Real prod evidence 2026-10-18 (dry-run x20): the newest rows missing
dates/amounts are NEWS (Cundinamarca, UdeA, Bogotá). Enriching them fills
junk (GTM JS as description, phantom funding "el 23" -> 23.0). The
backfill must skip news-like rows via looks_like_news and allow scoping
to true-call sources with repeatable --source-key=.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "backfill_enrich_opportunities.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backfill_enrich_opportunities", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None, SCRIPT_PATH
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_enrich_opportunities"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


class _Opp:
    def __init__(self, title, summary, url):
        self.title = title
        self.summary = summary
        self.official_url = url


class TestShouldSkipOpp:
    def test_news_item_is_skipped(self):
        assert (
            script.should_skip_opp(
                _Opp(
                    "Con más de 80 asistentes y 16 expertos, cerró en Medellín el Encuentro",
                    "Encuentro anual de egresados.",
                    "https://www.cundinamarca.gov.co/noticias/encuentro-egresados-2026",
                )
            )
            is True
        )

    def test_real_call_is_not_skipped(self):
        assert (
            script.should_skip_opp(
                _Opp(
                    "Convocatoria fondo concursable 2026",
                    "Apoyo a proyectos productivos. Cierre: 30 de noviembre de 2026.",
                    "https://www.cundinamarca.gov.co/convocatorias/fondo-2026",
                )
            )
            is False
        )


class TestParseArgs:
    def test_defaults(self):
        args = script.parse_args([])
        assert args["dry_run"] is True
        assert args["limit"] == 50
        assert args["source_keys"] == []

    def test_source_key_repeatable(self):
        args = script.parse_args(["--source-key=findeter-convocatorias", "--source-key=cost-open-calls"])
        assert args["source_keys"] == ["findeter-convocatorias", "cost-open-calls"]

    def test_limit_and_real_run(self):
        args = script.parse_args(["--limit=100", "--no-dry-run"])
        assert args["limit"] == 100
        assert args["dry_run"] is False
