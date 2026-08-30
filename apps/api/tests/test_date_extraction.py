"""Unit tests for parse_date_text / extract_dates — 022 DMY + year window."""
from __future__ import annotations

import pytest

from app.connectors.common import extract_dates, parse_date_text


class TestParseDateTextDMY:
    def test_spanish_de(self):
        dt = parse_date_text("15 de marzo de 2026")
        assert dt is not None and dt.year == 2026 and dt.month == 3 and dt.day == 15

    def test_spanish_without_de(self):
        dt = parse_date_text("30 abril 2026")
        assert dt is not None and dt.year == 2026 and dt.month == 4

    def test_slash_dmy(self):
        dt = parse_date_text("15/03/2026")
        assert dt is not None and dt.day == 15 and dt.month == 3

    def test_iso(self):
        dt = parse_date_text("2026-09-30")
        assert dt is not None and dt.year == 2026 and dt.month == 9

    def test_english(self):
        dt = parse_date_text("June 30, 2027")
        assert dt is not None and dt.year == 2027 and dt.month == 6

    def test_year_window_rejects_1999(self):
        assert parse_date_text("15/03/1999") is None

    def test_year_window_rejects_2030(self):
        assert parse_date_text("15/03/2030") is None

    def test_year_window_accepts_2025_2028(self):
        assert parse_date_text("01/01/2025") is not None
        assert parse_date_text("31/12/2028") is not None


class TestExtractDates:
    def test_desde_hasta_pair(self):
        od, cd = extract_dates("desde 15 de marzo 2026 hasta 30 abril 2026")
        assert od is not None and cd is not None
        assert od < cd
        assert od.day == 15 and cd.day == 30

    def test_desde_hasta_with_de(self):
        od, cd = extract_dates("desde 15 de marzo de 2026 hasta 30 de abril de 2026")
        assert od is not None and cd is not None

    def test_single_returns_none_open(self):
        od, cd = extract_dates("Fecha de cierre: 15 de marzo de 2026")
        assert od is None and cd is not None
        assert cd.day == 15

    def test_no_dates(self):
        od, cd = extract_dates("Sin fecha relevante")
        assert od is None and cd is None

    def test_multiple_sorted(self):
        od, cd = extract_dates("Apertura: 10 de enero de 2026 Cierre: 30 de septiembre de 2026")
        assert od is not None and cd is not None
        assert od.month == 1 and cd.month == 9

    def test_year_filter(self):
        od, cd = extract_dates("Fecha: 15/03/1999 y 30/09/2026")
        # 1999 filtered, only 2026 remains → single
        assert cd is not None and cd.year == 2026
        assert od is None

    def test_fecha_cierre_keyword(self):
        _, cd = extract_dates("Fecha de cierre: 30 de septiembre de 2026")
        assert cd is not None and cd.day == 30 and cd.month == 9

    def test_fp_less_than_2_percent(self):
        # Noise should not produce dates
        noises = ["tr", "<div>table</div>", "color: white;", "official website", "BudgetYearsColumns"]
        fps = sum(1 for n in noises for _ in [extract_dates(n)] if _[1] is not None)
        assert fps == 0
