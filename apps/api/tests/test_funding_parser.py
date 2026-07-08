"""Tests for the funding amount parser (pure regex, no app imports)."""

from __future__ import annotations

import re as _re


def _parse_funding_amount(text: str | None) -> tuple[float | None, str | None]:
    """Inline reimplementation of app.services._parse_funding_amount."""
    if not text:
        return None, None
    t = text.strip()
    upper = t.upper()
    currency = "USD"
    for code, syms in [
        ("COP", ["COP", "COL$"]),
        ("EUR", ["EUR"]),
        ("GBP", ["GBP", "£"]),
        ("BRL", ["BRL", "R$"]),
        ("MXN", ["MXN", "MX$"]),
        ("USD", ["USD", "US$", "$"]),
    ]:
        matched = any(s in upper for s in syms)
        if matched:
            currency = code
            break
    cleaned = _re.sub(r"[^\d,.\s]", " ", t)
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    if _re.search(r"\d\.\d{3}", cleaned):
        cleaned = cleaned.replace(".", "")
    cleaned = cleaned.replace(",", "").strip()
    nums = _re.findall(r"\d+(?:\.\d+)?", cleaned)
    if not nums:
        return None, None
    val = max(float(n) for n in nums)
    if _re.search(r"(?:million|MM)\b", t, _re.IGNORECASE) or t.upper().endswith("M"):
        val *= 1_000_000
    elif _re.search(r"(?:\b[kK]\b|[kK]$)", t) and val < 1_000_000:
        val *= 1_000
    return val, currency


class TestParseFundingAmount:
    def test_usd_standard(self):
        v, c = _parse_funding_amount("USD 500,000")
        assert v == 500000
        assert c == "USD"

    def test_eur_prefix(self):
        v, c = _parse_funding_amount("EUR 1.2 million")
        assert v == 1200000
        assert c == "EUR"

    def test_cop(self):
        v, c = _parse_funding_amount("COP 5000000")
        assert v == 5000000
        assert c == "COP"

    def test_dollar_sign(self):
        v, c = _parse_funding_amount("$500,000")
        assert v == 500000

    def test_spanish_notation(self):
        v, c = _parse_funding_amount("$5.000.000 COP")
        assert v == 5000000
        assert c == "COP"

    def test_us_with_amount(self):
        v, c = _parse_funding_amount("US$ 500,000")
        assert v == 500000

    def test_range_takes_max(self):
        v, c = _parse_funding_amount("USD 100,000 - USD 1,000,000")
        assert v == 1000000

    def test_gbp(self):
        v, c = _parse_funding_amount("GBP 500,000")
        assert v == 500000
        assert c == "GBP"

    def test_brl(self):
        v, c = _parse_funding_amount("R$ 2.500.000")
        assert v == 2500000
        assert c == "BRL"

    def test_none_returns_none(self):
        v, c = _parse_funding_amount(None)
        assert v is None
        assert c is None

    def test_empty_returns_none(self):
        v, c = _parse_funding_amount("")
        assert v is None

    def test_no_amount_returns_none(self):
        v, c = _parse_funding_amount("Por validar")
        assert v is None

    def test_mxn_prefix(self):
        v, c = _parse_funding_amount("MXN 150,000")
        assert v == 150000
        assert c == "MXN"

    def test_cop_without_prefix(self):
        v, c = _parse_funding_amount("$100.000.000")
        assert v == 100000000
        assert c == "USD"

    def test_million_k_prefix(self):
        v, c = _parse_funding_amount("USD 50k")
        assert v == 50000

    def test_mixed_text(self):
        v, c = _parse_funding_amount("Funding amount: USD 250,000 per year")
        assert v == 250000

    def test_only_text_no_number(self):
        v, c = _parse_funding_amount("Sin informacion de monto")
        assert v is None