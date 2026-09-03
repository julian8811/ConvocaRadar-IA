"""Unit tests for the shared field extractors in app.connectors.common.

Covers dash dates, open-date extraction, numeric funding normalization,
narrative labelled-section extraction, application-URL detection and the
consolidated structured-data reader. All helpers under test are pure
functions over text/HTML — no network access.
"""

from __future__ import annotations

from app.connectors.base import OpportunityCandidate
from app.connectors.common import (
    apply_extracted_fields,
    extract_application_url,
    extract_documents_required,
    extract_eligibility,
    extract_evaluation_criteria,
    extract_funding_amount,
    extract_funding_details,
    extract_labeled_section,
    extract_open_date,
    extract_page_fields,
    extract_requirements,
    extract_restrictions,
    extract_structured_data,
    fill_candidate_from_content,
    parse_date_text,
)

CONVOCATORIA_BULLETS = """CONVOCATORIA DE INNOVACIÓN 2026

¿Quién puede participar?
• Empresas colombianas con mínimo 2 años de operación
• Emprendedores mayores de 18 años
• Organizaciones sin ánimo de lucro legalmente constituidas

Requisitos:
1. Estar registrado en la Cámara de Comercio
2. Presentar estados financieros de los últimos dos años
3. No tener sanciones vigentes

Documentos requeridos:
- Formulario de inscripción diligenciado
- Certificado de existencia y representación legal
- Propuesta técnica en formato PDF

Criterios de evaluación:
a) Innovación de la propuesta
b) Impacto social esperado
c) Viabilidad financiera

Restricciones:
No podrán participar empleados de la entidad organizadora ni sus familiares.
"""

CONVOCATORIA_PROSE = """Beca de investigación aplicada.

Dirigido a investigadores con título de doctorado radicados en América Latina.
Se priorizarán propuestas interdisciplinarias.

Requisitos: contar con afiliación institucional vigente; acreditar dos
publicaciones arbitradas; dominio del idioma inglés.
"""


class TestParseDateTextDash:
    def test_dash_dmy(self):
        dt = parse_date_text("15-03-2026")
        assert dt is not None
        assert dt.day == 15 and dt.month == 3 and dt.year == 2026

    def test_dash_single_digit(self):
        dt = parse_date_text("5-9-2026")
        assert dt is not None
        assert dt.day == 5 and dt.month == 9 and dt.year == 2026

    def test_dash_out_of_window_rejected(self):
        assert parse_date_text("15-03-1999") is None

    def test_dash_iso_still_wins(self):
        dt = parse_date_text("2026-09-30")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 9 and dt.day == 30


class TestParseDateTextSpanishFlexible:
    def test_no_de_at_all(self):
        dt = parse_date_text("30 abril 2026")
        assert dt is not None
        assert dt.day == 30 and dt.month == 4 and dt.year == 2026

    def test_de_before_month_only(self):
        dt = parse_date_text("30 de abril 2026")
        assert dt is not None
        assert dt.day == 30 and dt.month == 4

    def test_de_before_year_only(self):
        dt = parse_date_text("30 abril de 2026")
        assert dt is not None
        assert dt.day == 30 and dt.month == 4

    def test_both_de(self):
        dt = parse_date_text("30 de abril de 2026")
        assert dt is not None
        assert dt.day == 30 and dt.month == 4

    def test_accented_month(self):
        dt = parse_date_text("1 septiembre 2026")
        assert dt is not None
        assert dt.month == 9

    def test_unknown_month_word_returns_none(self):
        assert parse_date_text("30 blahblah 2026") is None


class TestExtractOpenDate:
    def test_apertura_label(self):
        dt = extract_open_date("Apertura: 15 de marzo de 2026")
        assert dt is not None
        assert dt.day == 15 and dt.month == 3

    def test_fecha_de_apertura_label(self):
        # Day > 12 so the slash branch is unambiguous (it tries MDY before DMY).
        dt = extract_open_date("Fecha de apertura: 15/04/2026")
        assert dt is not None
        assert dt.day == 15 and dt.month == 4

    def test_desde_el_label(self):
        dt = extract_open_date("Las postulaciones se reciben desde el 10 abril 2026")
        assert dt is not None
        assert dt.day == 10 and dt.month == 4

    def test_disponible_a_partir_de(self):
        dt = extract_open_date("El formulario estara disponible a partir de 5 de mayo de 2026")
        assert dt is not None
        assert dt.month == 5

    def test_english_opening_date(self):
        dt = extract_open_date("Opening date: March 10, 2026")
        assert dt is not None
        assert dt.month == 3 and dt.day == 10

    def test_english_start_date(self):
        dt = extract_open_date("Start date: 22/05/2026")
        assert dt is not None
        assert dt.day == 22 and dt.month == 5

    def test_portuguese_data_de_abertura(self):
        dt = extract_open_date("Data de abertura: 20/03/2026")
        assert dt is not None
        assert dt.day == 20 and dt.month == 3

    def test_falls_back_to_extract_dates_open(self):
        dt = extract_open_date("desde 15 de marzo 2026 hasta 30 abril 2026")
        assert dt is not None
        assert dt.day == 15 and dt.month == 3

    def test_single_date_has_no_open(self):
        assert extract_open_date("Fecha de cierre: 30 de septiembre de 2026") is None

    def test_empty_returns_none(self):
        assert extract_open_date("") is None
        assert extract_open_date("Sin fechas") is None

    def test_prefers_labelled_over_sweep(self):
        text = "Cierre 30 de diciembre de 2026. Fecha de apertura: 15 de enero de 2026."
        dt = extract_open_date(text)
        assert dt is not None
        assert dt.month == 1 and dt.day == 15


class TestExtractFundingDetails:
    def test_returns_all_none_when_absent(self):
        assert extract_funding_details("Convocatoria sin monto definido") == (None, None, None)
        assert extract_funding_details("") == (None, None, None)
        assert extract_funding_details(None) == (None, None, None)  # type: ignore[arg-type]

    def test_reuses_extract_funding_amount_for_raw(self):
        text = "Presupuesto: USD 500.000 por proyecto"
        raw, _value, _currency = extract_funding_details(text)
        assert raw == extract_funding_amount(text)

    def test_en_locale_thousands(self):
        _raw, value, currency = extract_funding_details("Budget: USD 50,000.00 total")
        assert value == 50000.0
        assert currency == "USD"

    def test_es_locale_thousands(self):
        _raw, value, currency = extract_funding_details("Presupuesto: EUR 50.000,00 total")
        assert value == 50000.0
        assert currency == "EUR"

    def test_es_decimal_comma_only(self):
        _raw, value, _currency = extract_funding_details("Budget: USD 1.500,50 total")
        assert value == 1500.5

    def test_en_decimal_dot_only(self):
        _raw, value, _currency = extract_funding_details("Budget: USD 1,500.50 total")
        assert value == 1500.5

    def test_millones_de_pesos_no_country(self):
        raw, value, currency = extract_funding_details("Financiamiento hasta 100 millones de pesos")
        assert raw is not None
        assert value == 100_000_000
        assert currency is None

    def test_euro_million_english(self):
        _raw, value, currency = extract_funding_details("Budget: €2 million for the consortium")
        assert value == 2_000_000
        assert currency == "EUR"

    def test_mil_magnitude(self):
        _raw, value, _currency = extract_funding_details("Monto: 500 mil dolares")
        assert value == 500_000

    def test_mil_millones_magnitude(self):
        _raw, value, _currency = extract_funding_details("Monto: 2 mil millones de pesos chilenos")
        assert value == 2_000_000_000

    def test_billion_english(self):
        _raw, value, _currency = extract_funding_details("Funding: USD 1.5 billion available")
        assert value == 1_500_000_000

    def test_thousand_english(self):
        _raw, value, _currency = extract_funding_details("Funding: 250 thousand USD available")
        assert value == 250_000

    def test_portuguese_milhoes(self):
        _raw, value, currency = extract_funding_details("Investimento: R$ 3 milhões no total")
        assert value == 3_000_000
        assert currency == "BRL"

    def test_range_takes_max_and_keeps_raw(self):
        raw, value, currency = extract_funding_details("Funding: USD 100,000 - 1,000,000 per grant")
        assert value == 1_000_000
        assert currency == "USD"
        assert raw is not None
        assert "100,000" in raw and "1,000,000" in raw

    def test_range_with_hasta(self):
        _raw, value, _currency = extract_funding_details(
            "Monto: desde USD 10.000 hasta USD 250.000"
        )
        assert value == 250_000

    def test_currency_pesos_colombianos(self):
        _raw, _value, currency = extract_funding_details("Monto: 50.000.000 pesos colombianos")
        assert currency == "COP"

    def test_currency_dollar_sign_with_cop_suffix(self):
        _raw, _value, currency = extract_funding_details("Presupuesto: $5.000.000 COP")
        assert currency == "COP"

    def test_currency_bare_dollar_sign_is_ambiguous(self):
        _raw, value, currency = extract_funding_details("Presupuesto: $500.000")
        assert value == 500_000
        assert currency is None

    def test_currency_dolares(self):
        _raw, _value, currency = extract_funding_details("Monto: 500.000 dolares")
        assert currency == "USD"

    def test_currency_libras(self):
        _raw, _value, currency = extract_funding_details("Budget: £250,000 total")
        assert currency == "GBP"

    def test_currency_reais(self):
        _raw, _value, currency = extract_funding_details("Valor: 250.000 reais")
        assert currency == "BRL"

    def test_currency_mexican_chilean_peruvian(self):
        assert extract_funding_details("Monto: 500.000 pesos mexicanos")[2] == "MXN"
        assert extract_funding_details("Monto: 500.000 pesos chilenos")[2] == "CLP"
        assert extract_funding_details("Monto: 500.000 soles peruanos")[2] == "PEN"

    def test_currency_argentinos_uruguayos(self):
        assert extract_funding_details("Monto: 500.000 pesos argentinos")[2] == "ARS"
        assert extract_funding_details("Monto: 500.000 pesos uruguayos")[2] == "UYU"

    def test_accent_insensitive_currency(self):
        assert extract_funding_details("Monto: 500.000 DOLARES")[2] == "USD"

    def test_never_raises_on_weird_input(self):
        for weird in ("$", "...", "USD", "€€€", "1", "monto: , . ,", "\x00\x01"):
            assert isinstance(extract_funding_details(weird), tuple)


class TestExtractLabeledSection:
    def test_returns_empty_when_label_absent(self):
        assert extract_labeled_section("Texto sin secciones", ["requisitos"]) == []

    def test_returns_empty_on_empty_input(self):
        assert extract_labeled_section("", ["requisitos"]) == []
        assert extract_labeled_section(None, ["requisitos"]) == []  # type: ignore[arg-type]
        assert extract_labeled_section("Requisitos: algo", []) == []

    def test_accent_insensitive_label(self):
        items = extract_labeled_section(
            "CRITERIOS DE EVALUACION:\n• Pertinencia tecnica\n• Impacto",
            ["criterios de evaluación"],
        )
        assert items == ["Pertinencia tecnica", "Impacto"]

    def test_stops_at_paragraph_break(self):
        text = "Requisitos:\n• Ser mayor de edad\n\nOtra cosa que no pertenece a la seccion"
        items = extract_labeled_section(text, ["requisitos"])
        assert items == ["Ser mayor de edad"]

    def test_stops_at_next_known_heading_without_blank_line(self):
        text = "Requisitos: ser mayor de edad. Documentos requeridos: cedula de ciudadania."
        items = extract_labeled_section(text, ["requisitos"])
        joined = " ".join(items).lower()
        assert "mayor de edad" in joined
        assert "cedula" not in joined

    def test_max_chars_cap(self):
        text = "Requisitos: " + ("x" * 50 + ". ") * 20
        items = extract_labeled_section(text, ["requisitos"], max_chars=60)
        assert items
        assert all(len(item) <= 60 for item in items)

    def test_max_items_cap(self):
        bullets = "\n".join(f"• Requisito numero {n}" for n in range(20))
        items = extract_labeled_section("Requisitos:\n" + bullets, ["requisitos"], max_items=4)
        assert len(items) == 4

    def test_dedupes_preserving_order(self):
        text = "Requisitos:\n• Alfa\n• Beta\n• Alfa\n• Gamma"
        assert extract_labeled_section(text, ["requisitos"]) == ["Alfa", "Beta", "Gamma"]

    def test_drops_short_and_noise_items(self):
        text = "Requisitos:\n• ab\n• color: white;\n• Requisito valido y suficientemente largo"
        assert extract_labeled_section(text, ["requisitos"]) == [
            "Requisito valido y suficientemente largo"
        ]

    def test_never_raises_on_weird_input(self):
        for weird in ("{", "•••", "Requisitos:", "Requisitos:\n\n\n", "\x00"):
            assert isinstance(extract_labeled_section(weird, ["requisitos"]), list)


class TestNarrativeWrappersBullets:
    def test_eligibility(self):
        items = extract_eligibility(CONVOCATORIA_BULLETS)
        assert len(items) == 3
        assert items[0].startswith("Empresas colombianas")
        assert "Organizaciones sin ánimo de lucro legalmente constituidas" in items

    def test_requirements_numbered(self):
        items = extract_requirements(CONVOCATORIA_BULLETS)
        assert len(items) == 3
        assert items[0] == "Estar registrado en la Cámara de Comercio"
        assert not any(item.startswith(("1.", "2.", "3.")) for item in items)

    def test_documents_dash_bullets(self):
        items = extract_documents_required(CONVOCATORIA_BULLETS)
        assert len(items) == 3
        assert items[0] == "Formulario de inscripción diligenciado"
        assert not any(item.startswith("-") for item in items)

    def test_evaluation_criteria_letter_enumeration(self):
        items = extract_evaluation_criteria(CONVOCATORIA_BULLETS)
        assert len(items) == 3
        assert items[0] == "Innovación de la propuesta"
        assert not any(item.startswith(("a)", "b)", "c)")) for item in items)

    def test_restrictions_prose(self):
        items = extract_restrictions(CONVOCATORIA_BULLETS)
        assert len(items) == 1
        assert "empleados de la entidad organizadora" in items[0]

    def test_sections_do_not_bleed_into_each_other(self):
        eligibility = " ".join(extract_eligibility(CONVOCATORIA_BULLETS))
        assert "Cámara de Comercio" not in eligibility
        documents = " ".join(extract_documents_required(CONVOCATORIA_BULLETS))
        assert "Innovación de la propuesta" not in documents


class TestNarrativeWrappersProse:
    def test_eligibility_prose_dirigido_a(self):
        items = extract_eligibility(CONVOCATORIA_PROSE)
        assert items
        assert "doctorado" in " ".join(items)

    def test_requirements_prose_semicolons(self):
        items = extract_requirements(CONVOCATORIA_PROSE)
        assert len(items) >= 2
        joined = " ".join(items)
        assert "afiliación institucional" in joined
        assert "idioma inglés" in joined

    def test_absent_sections_return_empty(self):
        assert extract_documents_required(CONVOCATORIA_PROSE) == []
        assert extract_evaluation_criteria(CONVOCATORIA_PROSE) == []
        assert extract_restrictions(CONVOCATORIA_PROSE) == []

    def test_english_and_portuguese_labels(self):
        assert extract_eligibility("Who can apply:\n• Registered non-profits\n• Universities") == [
            "Registered non-profits",
            "Universities",
        ]
        assert extract_eligibility("Quem pode participar:\n• Institutos de pesquisa") == [
            "Institutos de pesquisa"
        ]
        assert extract_evaluation_criteria("Critérios de avaliação:\n• Mérito técnico") == [
            "Mérito técnico"
        ]

    def test_all_wrappers_safe_on_empty(self):
        for fn in (
            extract_eligibility,
            extract_requirements,
            extract_documents_required,
            extract_evaluation_criteria,
            extract_restrictions,
        ):
            assert fn("") == []
            assert fn("texto irrelevante") == []


BASE_URL = "https://fondo.org/convocatorias/innovacion-2026"

JSONLD_HTML = """<html><head>
<meta property="og:title" content="Titulo OpenGraph que no debe ganar">
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Grant",
 "name": "Convocatoria de Innovación 2026",
 "description": "Apoyo a proyectos de innovación en América Latina.",
 "startDate": "2026-03-15", "endDate": "2026-09-30",
 "funding": "USD 500,000",
 "url": "https://fondo.org/postular",
 "keywords": ["innovación", "tecnología"],
 "eligibleApplicant": ["Empresas", "Universidades"]}
</script></head><body><h1>Convocatoria</h1></body></html>"""

MICRODATA_HTML = """<html><body itemscope itemtype="https://schema.org/Grant">
<h1 itemprop="name">Beca de Investigación 2026</h1>
<p itemprop="description">Beca para investigadores posdoctorales.</p>
<meta itemprop="startDate" content="2026-04-01">
<meta itemprop="endDate" content="2026-10-15">
<span itemprop="fundingAmount">EUR 25.000</span>
<a itemprop="url" href="/aplicar">Aplicar</a>
<span itemprop="audience">Investigadores posdoctorales</span>
<span itemprop="keywords">investigación, ciencia</span>
</body></html>"""

OG_ONLY_HTML = """<html><head>
<meta property="og:title" content="Fondo Cultural 2026">
<meta property="og:description" content="Apoyo a proyectos culturales.">
</head><body><p>Sin enlaces relevantes.</p></body></html>"""

MALFORMED_JSONLD_HTML = """<html><head>
<script type="application/ld+json">{ esto no es json,,, }</script>
<meta name="description" content="Descripcion de respaldo">
</head><body></body></html>"""


class TestExtractApplicationUrl:
    def test_relative_apply_link_is_absolutized(self):
        html_doc = '<a href="/postulacion">Postular ahora</a>'
        assert extract_application_url(html_doc, BASE_URL) == "https://fondo.org/postulacion"

    def test_google_forms_host_is_accepted_cross_domain(self):
        html_doc = (
            '<a href="https://docs.google.com/forms/d/e/abc/viewform">'
            "Formulario de inscripción</a>"
        )
        url = extract_application_url(html_doc, BASE_URL)
        assert url == "https://docs.google.com/forms/d/e/abc/viewform"

    def test_prefers_apply_link_over_generic_nav(self):
        html_doc = """
        <nav><a href="/inicio">Inicio</a><a href="/contacto">Contacto</a></nav>
        <a href="/formulario-de-postulacion">Inscribirse a la convocatoria</a>
        """
        assert (
            extract_application_url(html_doc, BASE_URL)
            == "https://fondo.org/formulario-de-postulacion"
        )

    def test_uses_title_attribute(self):
        html_doc = '<a href="/f/9" title="Formulario de aplicación">Ver más</a>'
        assert extract_application_url(html_doc, BASE_URL) == "https://fondo.org/f/9"

    def test_typeform_host(self):
        html_doc = '<a href="https://midominio.typeform.com/to/abc123">Aplica aquí</a>'
        assert extract_application_url(html_doc, BASE_URL) == (
            "https://midominio.typeform.com/to/abc123"
        )

    def test_negative_no_plausible_link(self):
        html_doc = '<nav><a href="/inicio">Inicio</a><a href="/nosotros">Nosotros</a></nav>'
        assert extract_application_url(html_doc, BASE_URL) is None

    def test_skips_non_http_schemes(self):
        html_doc = """
        <a href="mailto:postular@fondo.org">Postular</a>
        <a href="tel:+5712345678">Inscribirse</a>
        <a href="javascript:void(0)">Aplicar</a>
        <a href="#postulacion">Postulación</a>
        """
        assert extract_application_url(html_doc, BASE_URL) is None

    def test_empty_and_malformed_html(self):
        assert extract_application_url("", BASE_URL) is None
        assert extract_application_url("<<<>>>", BASE_URL) is None
        assert extract_application_url(None, BASE_URL) is None  # type: ignore[arg-type]

    def test_english_apply_now(self):
        html_doc = '<a href="/apply">Apply now</a>'
        assert extract_application_url(html_doc, BASE_URL) == "https://fondo.org/apply"

    def test_portuguese_inscrever(self):
        html_doc = '<a href="/inscricoes">Inscrever-se</a>'
        assert extract_application_url(html_doc, BASE_URL) == "https://fondo.org/inscricoes"


class TestExtractStructuredData:
    def test_expected_keys_always_present(self):
        data = extract_structured_data("")
        assert set(data) == {
            "title",
            "summary",
            "open_date",
            "close_date",
            "funding_raw",
            "funding_value",
            "funding_currency",
            "application_url",
            "categories",
            "eligible_applicants",
        }

    def test_jsonld_fixture(self):
        data = extract_structured_data(JSONLD_HTML, BASE_URL)
        assert data["title"] == "Convocatoria de Innovación 2026"
        assert data["summary"] == "Apoyo a proyectos de innovación en América Latina."
        assert data["open_date"] is not None and data["open_date"].month == 3  # type: ignore[union-attr]
        assert data["close_date"] is not None and data["close_date"].month == 9  # type: ignore[union-attr]
        assert data["funding_value"] == 500_000
        assert data["funding_currency"] == "USD"
        assert data["application_url"] == "https://fondo.org/postular"
        assert data["categories"] == ["innovación", "tecnología"]
        assert data["eligible_applicants"] == ["Empresas", "Universidades"]

    def test_jsonld_wins_over_opengraph(self):
        data = extract_structured_data(JSONLD_HTML, BASE_URL)
        assert data["title"] == "Convocatoria de Innovación 2026"

    def test_microdata_fixture(self):
        data = extract_structured_data(MICRODATA_HTML, BASE_URL)
        assert data["title"] == "Beca de Investigación 2026"
        assert data["summary"] == "Beca para investigadores posdoctorales."
        assert data["open_date"] is not None and data["open_date"].month == 4  # type: ignore[union-attr]
        assert data["close_date"] is not None and data["close_date"].day == 15  # type: ignore[union-attr]
        assert data["funding_value"] == 25_000
        assert data["funding_currency"] == "EUR"
        assert data["application_url"] == "https://fondo.org/aplicar"
        assert data["categories"] == ["investigación", "ciencia"]
        assert data["eligible_applicants"] == ["Investigadores posdoctorales"]

    def test_opengraph_only_fixture(self):
        data = extract_structured_data(OG_ONLY_HTML, BASE_URL)
        assert data["title"] == "Fondo Cultural 2026"
        assert data["summary"] == "Apoyo a proyectos culturales."
        assert data["open_date"] is None
        assert data["close_date"] is None
        assert data["funding_raw"] is None
        assert data["application_url"] is None
        assert data["categories"] == []

    def test_malformed_json_is_skipped_silently(self):
        data = extract_structured_data(MALFORMED_JSONLD_HTML, BASE_URL)
        assert data["title"] is None
        assert data["summary"] == "Descripcion de respaldo"

    def test_jsonld_list_payload(self):
        html_doc = (
            '<script type="application/ld+json">'
            '[{"@type": "WebPage"}, {"@type": "Grant", "name": "Fondo Verde"}]'
            "</script>"
        )
        assert extract_structured_data(html_doc)["title"] == "Fondo Verde"

    def test_jsonld_graph_payload(self):
        html_doc = (
            '<script type="application/ld+json">'
            '{"@graph": [{"@type": "Grant", "name": "Fondo Azul", '
            '"validThrough": "2026-11-20"}]}'
            "</script>"
        )
        data = extract_structured_data(html_doc)
        assert data["title"] == "Fondo Azul"
        assert data["close_date"] is not None and data["close_date"].day == 20  # type: ignore[union-attr]

    def test_jsonld_nested_funding_object(self):
        html_doc = (
            '<script type="application/ld+json">'
            '{"@type": "Grant", "name": "X", "funding": {"value": 75000, "currency": "COP"}}'
            "</script>"
        )
        data = extract_structured_data(html_doc)
        assert data["funding_value"] == 75000
        assert data["funding_currency"] == "COP"
        assert data["funding_raw"] is not None

    def test_validfrom_maps_to_open_date(self):
        html_doc = (
            '<script type="application/ld+json">'
            '{"@type": "Grant", "validFrom": "2026-02-10", "validThrough": "2026-08-20"}'
            "</script>"
        )
        data = extract_structured_data(html_doc)
        assert data["open_date"] is not None and data["open_date"].month == 2  # type: ignore[union-attr]
        assert data["close_date"] is not None and data["close_date"].month == 8  # type: ignore[union-attr]

    def test_application_url_falls_back_to_anchor_scan(self):
        html_doc = '<html><body><a href="/postular">Postular ahora</a></body></html>'
        data = extract_structured_data(html_doc, BASE_URL)
        assert data["application_url"] == "https://fondo.org/postular"

    def test_never_raises_on_weird_input(self):
        for weird in (None, "", "<<<", "\x00", '<script type="application/ld+json"></script>'):
            assert isinstance(extract_structured_data(weird), dict)  # type: ignore[arg-type]


class TestSpanishDateComma:
    def test_day_de_month_comma_year(self):
        dt = parse_date_text("3 de julio, 2026")
        assert dt is not None
        assert dt.day == 3 and dt.month == 7 and dt.year == 2026

    def test_cierre_label_with_comma_and_time(self):
        dt = parse_date_text("Cierre: 14 de agosto, 2026 - 13:00")
        assert dt is not None
        assert dt.day == 14 and dt.month == 8

    def test_inicio_label_extracts_open_date(self):
        dt = extract_open_date("Inicio: 3 de julio, 2026")
        assert dt is not None
        assert dt.day == 3 and dt.month == 7


RICH_DETAIL_HTML = """<html><body>
<article>
<h1>Convocatoria de Innovación 2026</h1>
<p>El Ministerio abre la convocatoria para cofinanciar proyectos de innovación empresarial.</p>
<p>Apertura: 15 de marzo de 2026. Fecha de cierre: 30 de septiembre de 2026.</p>
<p>Monto: hasta 500 millones de pesos colombianos.</p>
<p>¿Quién puede participar?</p>
<ul>
<li>Empresas colombianas legalmente constituidas</li>
<li>Centros de investigación reconocidos</li>
</ul>
<p>Requisitos:</p>
<ul>
<li>Estar registrado en el sistema nacional</li>
<li>Contar con estados financieros auditados</li>
</ul>
<p>Documentos requeridos:</p>
<ul>
<li>Certificado de existencia y representación legal</li>
</ul>
<p>Criterios de evaluación:</p>
<ul>
<li>Pertinencia técnica de la propuesta</li>
<li>Impacto regional esperado</li>
</ul>
<p>Restricciones:</p>
<ul>
<li>No podrán participar entidades sancionadas fiscalmente</li>
</ul>
<p><a href="/postular">Postular ahora</a></p>
</article>
</body></html>"""


class TestExtractPageFields:
    def test_captures_dates_funding_narrative_and_apply_url(self):
        data = extract_page_fields(
            html=RICH_DETAIL_HTML,
            page_url="https://fondo.org/convocatoria",
        )
        assert data["title"] == "Convocatoria de Innovación 2026"
        assert data["open_date"] is not None and data["open_date"].month == 3
        assert data["close_date"] is not None and data["close_date"].month == 9
        assert data["funding_amount_value"] == 500_000_000
        assert data["funding_amount_currency"] == "COP"
        assert data["funding_amount_raw"]
        assert any("empresas" in item.lower() for item in data["eligible_applicants"])
        assert data["requirements"]
        assert data["documents_required"]
        assert data["evaluation_criteria"]
        assert data["restrictions"]
        assert data["application_url"] == "https://fondo.org/postular"
        assert data["raw_text"] and len(data["raw_text"]) > 80

    def test_empty_input_returns_skeleton(self):
        data = extract_page_fields(html="", text="")
        assert data["title"] is None
        assert data["eligible_applicants"] == []
        assert data["funding_amount_raw"] is None


class TestFillCandidateFromContent:
    def test_fills_gaps_without_overwriting(self):
        candidate = OpportunityCandidate(
            title="Título del listado",
            entity="Minciencias",
            country="Colombia",
            official_url="https://fondo.org/convocatoria",
            summary="Resumen corto del listado",
            funding_amount_raw="ya extraído",
        )
        filled = fill_candidate_from_content(
            candidate,
            html=RICH_DETAIL_HTML,
            page_url="https://fondo.org/convocatoria",
        )
        assert filled.title == "Título del listado"
        assert filled.funding_amount_raw == "ya extraído"
        assert filled.close_date is not None
        assert filled.open_date is not None
        assert filled.eligible_applicants
        assert filled.application_url == "https://fondo.org/postular"

    def test_apply_extracted_fields_prefers_detail_title(self):
        candidate = OpportunityCandidate(
            title="Card",
            entity="E",
            country="Colombia",
            official_url="https://fondo.org/x",
        )
        merged = apply_extracted_fields(
            candidate,
            {"title": "Título largo de la ficha", "close_date": parse_date_text("30/09/2026")},
            prefer_extracted_text=True,
        )
        assert merged.title == "Título largo de la ficha"
        assert merged.close_date is not None
