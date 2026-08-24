"""Tests for source optimization: enrichment, tiering, title cleanup, country inference."""

from __future__ import annotations



from app.connectors.common import clean_opportunity_title, infer_country_from_entity


# ── 1. Title cleanup ────────────────────────────────────────────────────────


class TestCleanTitle:
    def test_truncates_long_title_with_instituicao(self):
        raw = "Bolsa de PD em Química Orgânica / Biologia Celular / Físico-Química Instituição: Instituto de Química, Universidade de São Paulo (IQ-USP) Cidade: São Paulo Inscrições até: 24/07/2026 " * 2
        cleaned = clean_opportunity_title(raw)
        assert len(cleaned) <= 150
        assert "Bolsa de PD em Química Orgânica" in cleaned
        assert "Instituição" not in cleaned

    def test_keeps_short_titles(self):
        title = "Convocatoria Minciencias 2026"
        assert clean_opportunity_title(title) == title

    def test_cleans_instituicao_pattern(self):
        raw = "Bolsa de Doutorado em Física Instituição: Instituto de Física Cidade: São Paulo " * 3
        cleaned = clean_opportunity_title(raw)
        assert "Instituição" not in cleaned
        assert "Cidade" not in cleaned

    def test_cleans_inscricoes_pattern(self):
        raw = "Bolsa de PD em Genômica Instituição: USP and some more text here to make it long enough to trigger the truncation logic " * 2
        cleaned = clean_opportunity_title(raw)
        assert "Instituição" not in cleaned

    def test_empty_title_returns_empty(self):
        assert clean_opportunity_title("") == ""
        assert clean_opportunity_title(None) == ""


# ── 2. Country inference ────────────────────────────────────────────────────


class TestInferCountry:
    def test_infers_from_known_entity(self):
        assert infer_country_from_entity("Findeter", None) == "Colombia"
        assert infer_country_from_entity("APC Colombia", None) == "Colombia"
        assert infer_country_from_entity("FAPESP Brasil", None) == "Brazil"
        assert infer_country_from_entity("CONICET Argentina", None) == "Argentina"
        assert infer_country_from_entity("UK Research and Innovation", None) == "United Kingdom"
        assert infer_country_from_entity("Horizon Europe SEDIA API", None) == "European Union"

    def test_infers_from_domain(self):
        assert infer_country_from_entity("Test Entity", "www.findeter.gov.co") == "Colombia"
        assert infer_country_from_entity("Test Entity", "www.fapesp.br") == "Brazil"
        assert infer_country_from_entity("Test Entity", "www.nsf.gov") == "United States"
        assert infer_country_from_entity("Test Entity", "www.unesco.org") == "International"

    def test_returns_unknown_for_unrecognized(self):
        cnt = infer_country_from_entity("Unknown Entity", "https://unknown.example.com")
        assert cnt == "Sin dato" or cnt == "Por validar"
