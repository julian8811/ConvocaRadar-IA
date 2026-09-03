"""Tests: narrative fields must be extracted and must survive enrichment.

``eligible_applicants``, ``evaluation_criteria`` and ``restrictions`` were read
by ``enrich_opportunity_payload`` but never produced by the extraction schema,
so those columns were empty for every row in the database. These tests pin both
ends: the extractor produces them, and enrichment carries them through.
"""

from __future__ import annotations

from app.core.ai import build_local_extraction
from app.schemas.ai import AiOpportunityExtract
from app.services.opportunity import OpportunityCreate, enrich_opportunity_payload

CONVOCATORIA = """
Convocatoria Nacional de Innovación 2026

Descripción
El Ministerio abre la convocatoria para cofinanciar proyectos de innovación
empresarial con enfoque regional en todo el territorio nacional.

¿Quién puede participar?
- Empresas legalmente constituidas en Colombia
- Centros de investigación reconocidos
- Universidades acreditadas

Requisitos
- Estar registrado en el sistema nacional
- Contar con estados financieros auditados

Documentos requeridos
- Certificado de existencia y representación legal
- Propuesta técnica en el formato oficial

Criterios de evaluación
- Pertinencia técnica de la propuesta
- Impacto regional esperado
- Capacidad del equipo ejecutor

Restricciones
- No podrán participar entidades sancionadas fiscalmente
- No se aceptan propuestas presentadas por personas naturales

Fecha de cierre: 30 de septiembre de 2026
Monto: hasta 500 millones de pesos colombianos
"""


class TestAiExtractSchema:
    def test_schema_accepts_narrative_fields(self):
        extract = AiOpportunityExtract(
            title="t",
            entity="e",
            country="Colombia",
            category=[],
            status="open",
            requirements=[],
            documents_required=[],
            summary="s",
            risks=[],
            recommendation="r",
            confidence=0.8,
            eligible_applicants=["Empresas"],
            evaluation_criteria=["Pertinencia"],
            restrictions=["No sancionadas"],
            application_url="https://example.gov.co/postular",
        )
        assert extract.eligible_applicants == ["Empresas"]
        assert extract.evaluation_criteria == ["Pertinencia"]
        assert extract.restrictions == ["No sancionadas"]
        assert extract.application_url == "https://example.gov.co/postular"

    def test_narrative_fields_default_to_empty(self):
        extract = AiOpportunityExtract(
            title="t",
            entity="e",
            country="Colombia",
            category=[],
            status="open",
            requirements=[],
            documents_required=[],
            summary="s",
            risks=[],
            recommendation="r",
            confidence=0.8,
        )
        assert extract.eligible_applicants == []
        assert extract.evaluation_criteria == []
        assert extract.restrictions == []
        assert extract.application_url is None


class TestLocalExtraction:
    def test_extracts_eligible_applicants(self):
        data = build_local_extraction(CONVOCATORIA)
        joined = " ".join(data["eligible_applicants"]).lower()
        assert "empresas legalmente constituidas" in joined

    def test_extracts_evaluation_criteria(self):
        data = build_local_extraction(CONVOCATORIA)
        joined = " ".join(data["evaluation_criteria"]).lower()
        assert "pertinencia" in joined
        assert "impacto regional" in joined

    def test_extracts_restrictions(self):
        data = build_local_extraction(CONVOCATORIA)
        joined = " ".join(data["restrictions"]).lower()
        assert "sancionadas" in joined

    def test_preserves_accents_and_casing(self):
        """Items are for display, so they must not be accent-stripped."""
        data = build_local_extraction(CONVOCATORIA)
        joined = " ".join(data["evaluation_criteria"])
        assert "é" in joined or "ó" in joined or "í" in joined

    def test_narrative_fields_absent_yields_empty_lists(self):
        data = build_local_extraction("Texto corto sin secciones estructuradas.")
        assert data["eligible_applicants"] == []
        assert data["evaluation_criteria"] == []
        assert data["restrictions"] == []

    def test_extracts_funding_value_and_currency(self):
        data = build_local_extraction(CONVOCATORIA)
        assert data["funding_amount_value"] == 500_000_000
        assert data["funding_amount_currency"] == "COP"


class TestEnrichmentCarriesNarrativeFields:
    async def test_enrichment_populates_narrative_fields(self):
        payload = OpportunityCreate(
            title="Convocatoria Nacional de Innovación 2026",
            entity="Ministerio",
            country="Colombia",
            official_url="https://example.gov.co/conv",
            raw_text=CONVOCATORIA,
            summary="",
        )
        enriched = await enrich_opportunity_payload(payload)
        assert enriched.eligible_applicants, "eligible_applicants must be populated"
        assert enriched.evaluation_criteria, "evaluation_criteria must be populated"
        assert enriched.restrictions, "restrictions must be populated"

    async def test_enrichment_does_not_overwrite_scraped_narrative_fields(self):
        payload = OpportunityCreate(
            title="Convocatoria Nacional de Innovación 2026",
            entity="Ministerio",
            country="Colombia",
            official_url="https://example.gov.co/conv",
            raw_text=CONVOCATORIA,
            summary="",
            eligible_applicants=["Valor del scraper"],
            evaluation_criteria=["Criterio del scraper"],
            restrictions=["Restricción del scraper"],
        )
        enriched = await enrich_opportunity_payload(payload)
        assert enriched.eligible_applicants == ["Valor del scraper"]
        assert enriched.evaluation_criteria == ["Criterio del scraper"]
        assert enriched.restrictions == ["Restricción del scraper"]
