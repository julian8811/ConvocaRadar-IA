"""Tests: separate "this summary is junk" from "this summary is short".

``is_thin_or_metadata_summary`` doubled as both checks by rejecting anything
below ``extraction_thin_threshold`` (200 chars). That made every genuine
one-or-two-sentence summary look like metadata junk, so the pipeline refused to
keep it and reports hid it. The junk test and the enrichment trigger are
different questions and must not share a threshold.
"""

from __future__ import annotations

from app.services.opportunity import is_thin_or_metadata_summary, summary_needs_enrichment

# 187 chars — a real, substantive summary that sits below the 200-char
# enrichment threshold.
GOOD_SHORT = (
    "Department of State's Embassy Ottawa announces an open competition to "
    "implement a program to connect U.S. citizen talent with Canadian "
    "audiences and institutions on topics of mutual interest."
)

GOOD_SHORT_ES = (
    "El Ministerio abre una convocatoria para cofinanciar proyectos de "
    "innovación empresarial con enfoque regional."
)


class TestJunkDetection:
    def test_substantive_short_summary_is_not_junk(self):
        assert not is_thin_or_metadata_summary(GOOD_SHORT)

    def test_substantive_short_spanish_summary_is_not_junk(self):
        assert not is_thin_or_metadata_summary(GOOD_SHORT_ES)

    def test_truly_short_text_is_junk(self):
        assert is_thin_or_metadata_summary("short")
        assert is_thin_or_metadata_summary("Convocatoria abierta")

    def test_empty_is_junk(self):
        assert is_thin_or_metadata_summary("")
        assert is_thin_or_metadata_summary(None)

    def test_metadata_shapes_remain_junk(self):
        assert is_thin_or_metadata_summary("Number: O-COPS-2026-172583 | Agency: Simpler Grants")
        assert is_thin_or_metadata_summary("DFOP0019426 | DOS-DRL | Status: posted")
        assert is_thin_or_metadata_summary("sitemap entry — lastmod: 2026-07-21")
        assert is_thin_or_metadata_summary(
            "An official website of the United States government " + "x" * 200
        )
        assert is_thin_or_metadata_summary(
            "Eligible Applicants: Others. Funding Opportunity Title: Something. Category: Other."
        )


class TestEnrichmentTrigger:
    def test_short_but_good_summary_still_wants_enrichment(self):
        """Not junk, but short enough that we should still try to enrich it."""
        assert summary_needs_enrichment(GOOD_SHORT)

    def test_long_summary_does_not_need_enrichment(self):
        assert not summary_needs_enrichment("x" * 250 + " frase con contenido real.")

    def test_junk_always_needs_enrichment(self):
        assert summary_needs_enrichment("Number: 123 | Agency: Y")
        assert summary_needs_enrichment(None)
