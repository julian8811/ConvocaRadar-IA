import json

import pytest

from worker.connectors.base import RawSourceResult
from worker.connectors.common import fetch_httpx_text, is_allowed_host
from worker.connectors.apc_colombia import ApcColombiaConnector
from worker.connectors.api import ApiConnector
from worker.connectors.factory import connector_for
from worker.connectors.generic_html import GenericHtmlConnector
from worker.connectors.eu_funding_tenders import EuFundingTendersConnector
from worker.connectors.grants_gov import GrantsGovConnector
from worker.connectors.grants_gov_rss import GrantsGovRssConnector
from worker.connectors.icetex import IcetexConnector
from worker.connectors.innovamos import InnovamosConnector
from worker.connectors.hybrid import HybridConnector
from worker.connectors.innpulsa import InnpulsaConnector
from worker.connectors.minciencias import MincienciasConnector
from worker.connectors.mineducacion import MineducacionConnector
from worker.connectors.nsf import NSFFundingConnector
from worker.connectors.nsf import NSFFundingRssConnector
from worker.connectors.manual import ManualConnector
from worker.connectors.pdf import PdfConnector
from worker.connectors.rss import RssConnector
from worker.connectors.undef import UNDEFConnector
from worker.connectors.unesco import UNESCOConnector
from worker.connectors.simpler_grants import SimplerGrantsConnector
from worker.connectors.ukri import UKRIConnector
from worker.connectors.unwomen_innovate import UnwomenInnovateConnector


@pytest.mark.asyncio
async def test_grants_gov_connector_parses_search2_fixture() -> None:
    payload = {
        "errorcode": 0,
        "msg": "Webservice Succeeds",
        "data": {
            "hitCount": 1,
            "oppHits": [
                {
                    "id": "219999",
                    "number": "TEST-ABC-20231011-OPP1",
                    "title": "AI Research Capacity Building",
                    "agencyCode": "HHS",
                    "agencyName": "Health & Human Services",
                    "openDate": "10/11/2025",
                    "closeDate": "12/31/2026",
                    "oppStatus": "posted",
                    "docType": "synopsis",
                    "alnist": ["93.223"],
                }
            ],
        },
    }
    connector = GrantsGovConnector()
    raw = RawSourceResult(
        source_key="grants-gov",
        url="https://api.grants.gov/v1/api/search2",
        content=json.dumps(payload),
        content_type="application/json",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "AI Research Capacity Building"
    assert candidate.entity == "Health & Human Services"
    assert candidate.country == "United States"
    assert candidate.official_url == "https://www.grants.gov/search-results-detail/219999"
    assert candidate.open_date is not None
    assert candidate.close_date is not None
    assert "grants" in candidate.categories
    assert (await connector.validate(candidate)).ok


def test_connector_factory_selects_grants_gov() -> None:
    connector = connector_for("grants-gov", "https://api.grants.gov/v1/api/search2")
    assert isinstance(connector, GrantsGovConnector)


def test_connector_factory_routes_by_source_type() -> None:
    assert isinstance(connector_for("custom-api", "https://example.org/api", "api"), ApiConnector)
    assert isinstance(connector_for("custom-pdf", "https://example.org/file.pdf", "pdf"), PdfConnector)
    assert isinstance(connector_for("custom-manual", "https://example.org/manual", "manual"), ManualConnector)
    assert isinstance(connector_for("custom-hybrid", "https://example.org/calls", "hybrid"), HybridConnector)
    assert isinstance(connector_for("grants-gov", "https://api.grants.gov/v1/api/search2", "api"), GrantsGovConnector)
    assert isinstance(connector_for("icetex-vigentes", "https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes"), IcetexConnector)
    assert isinstance(connector_for("mineducacion-becas", "https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias"), MineducacionConnector)
    assert isinstance(connector_for("innovamos-global-innovation-fund", "https://www.innovamos.gov.co/instrumentos/convocatoria-subvenciones-a-proyectos-en-alianza-con"), InnovamosConnector)
    assert isinstance(connector_for("undef", "https://www.un.org/democracyfund/en/apply-for-funding"), UNDEFConnector)
    assert isinstance(connector_for("nsf-funding", "https://www.nsf.gov/funding"), NSFFundingConnector)
    assert isinstance(connector_for("ukri-opportunities", "https://www.ukri.org/opportunity/"), UKRIConnector)
    assert isinstance(connector_for("unesco-call-for-proposals", "https://www.unesco.org/en/articles/call-proposals"), UNESCOConnector)


@pytest.mark.asyncio
async def test_api_connector_parses_nested_items_fixture() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "name": "Nested API Call 2026",
                    "link": "/api/calls/nested-api-call-2026",
                    "description": "Funding for research and innovation",
                    "country": "Colombia",
                    "categories": ["grants", "research"],
                }
            ]
        }
    }
    connector = ApiConnector("custom-api", "https://example.org/api")
    raw = RawSourceResult(
        source_key="custom-api",
        url="https://example.org/api",
        content=json.dumps(payload),
        content_type="application/json",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].title == "Nested API Call 2026"
    assert candidates[0].official_url == "https://example.org/api/calls/nested-api-call-2026"
    assert "research" in candidates[0].categories


@pytest.mark.asyncio
async def test_hybrid_connector_detects_rss_by_content_type() -> None:
    xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <rss version=\"2.0\">
      <channel>
        <item>
          <title>Hybrid Feed Grant</title>
          <link>https://example.org/hybrid/grant</link>
          <description>Funding for open innovation.</description>
        </item>
      </channel>
    </rss>
    """
    connector = HybridConnector("custom-hybrid", "https://example.org/calls")
    raw = RawSourceResult(
        source_key="custom-hybrid",
        url="https://example.org/calls",
        content=xml,
        content_type="application/rss+xml",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].title == "Hybrid Feed Grant"
    assert candidates[0].official_url == "https://example.org/hybrid/grant"


@pytest.mark.asyncio
async def test_pdf_connector_parses_text_fixture(monkeypatch) -> None:
    class FakePage:
        def extract_text(self):
            return "Open Call 2026\nResearch and innovation grant for Colombia.\nClose date 2026-12-01."

    class FakeReader:
        def __init__(self, *_args, **_kwargs):
            self.metadata = type("Meta", (), {"title": "Open Call 2026"})()
            self.pages = [FakePage()]

    monkeypatch.setattr("worker.connectors.pdf.PdfReader", FakeReader)
    connector = PdfConnector("custom-pdf", "https://example.org/call.pdf")
    raw = RawSourceResult(
        source_key="custom-pdf",
        url="https://example.org/call.pdf",
        content="binary pdf placeholder",
        content_type="application/pdf",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Open Call 2026"
    assert candidate.country == "Colombia"
    assert candidate.close_date is not None
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_pdf_connector_parses_multiple_sections_fixture(monkeypatch) -> None:
    class FakePage:
        def extract_text(self):
            return (
                "Open Call 2026\nResearch and innovation grant for Colombia.\nClose date 2026-12-01.\n\n"
                "Second Call 2026\nFunding for education and science.\nClose date 2026-11-15."
            )

    class FakeReader:
        def __init__(self, *_args, **_kwargs):
            self.metadata = type("Meta", (), {"title": "Open Call 2026"})()
            self.pages = [FakePage()]

    monkeypatch.setattr("worker.connectors.pdf.PdfReader", FakeReader)
    connector = PdfConnector("custom-pdf", "https://example.org/call.pdf")
    raw = RawSourceResult(
        source_key="custom-pdf",
        url="https://example.org/call.pdf",
        content="binary pdf placeholder",
        content_type="application/pdf",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) >= 2
    assert candidates[0].title == "Open Call 2026"
    assert candidates[1].title == "Second Call 2026"


@pytest.mark.asyncio
async def test_grants_gov_connector_falls_back_to_html_search_fixture() -> None:
    html = r"""
    <script>self.__next_f.push([1,"
    {\"href\":\"/opportunity/21f5b3ac-4760-44be-a577-936e8915ea57\",\"id\":\"search-result-link-1-1\",\"children\":\"Public Diplomacy Section Praia: Small Grants Program\"}
    {\"children\":[\"Number\",\":\"]}],\" \",\"PAS-PRAIA-FY26-01\"}
    {\"children\":\"Agency\"}],\"children\":\"U.S. Mission to Cabo Verde\"}
    {\"children\":\"Close date\"}],\" \",\"Jul 1, 2026\"}
    {\"children\":\"Posted date\"}],\" \",\"Jun 1, 2026\"}
    "</script>
    """
    connector = GrantsGovConnector("https://www.grants.gov/search-grants")
    raw = RawSourceResult(
        source_key="grants-gov",
        url="https://www.grants.gov/search-grants",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Public Diplomacy Section Praia: Small Grants Program"
    assert candidate.official_url == "https://simpler.grants.gov/opportunity/21f5b3ac-4760-44be-a577-936e8915ea57"
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_rss_connector_parses_feed_fixture() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Grant Opportunities</title>
        <item>
          <title>Rural Innovation Grant</title>
          <link>https://www.grants.gov/search-results-detail/12345</link>
          <description><![CDATA[Funding for rural innovation projects.]]></description>
          <category>Community Development</category>
          <pubDate>Fri, 19 Jun 2026 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    connector = RssConnector("grants-gov-rss", "https://www.grants.gov/rss/GG_OppModByCategory.xml")
    raw = RawSourceResult(
        source_key="grants-gov-rss",
        url="https://www.grants.gov/rss/GG_OppModByCategory.xml",
        content=xml,
        content_type="application/rss+xml",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Rural Innovation Grant"
    assert candidate.summary == "Funding for rural innovation projects."
    assert candidate.official_url == "https://www.grants.gov/search-results-detail/12345"
    assert candidate.open_date is not None
    assert "rss" in candidate.categories
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_grants_gov_rss_connector_parses_feed_fixture() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Grants.gov Forecast</title>
        <item>
          <title>STEM Education Partnership Grant</title>
          <link>https://www.grants.gov/search-results-detail/99999</link>
          <description><![CDATA[Support for STEM education partnerships.]]></description>
          <category>Education</category>
          <pubDate>Fri, 19 Jun 2026 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    connector = GrantsGovRssConnector("grants-gov-forecast", "https://www.grants.gov/rss/GG_ForecastOpportunities.xml")
    raw = RawSourceResult(
        source_key="grants-gov-forecast",
        url="https://www.grants.gov/rss/GG_ForecastOpportunities.xml",
        content=xml,
        content_type="application/rss+xml",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "STEM Education Partnership Grant"
    assert candidate.official_url == "https://www.grants.gov/search-results-detail/99999"
    assert candidate.entity == "grants-gov-forecast"
    assert (await connector.validate(candidate)).ok


def test_connector_factory_selects_rss_by_key_or_url() -> None:
    by_key = connector_for("grants-gov-rss", "https://www.grants.gov/rss/GG_OppModByCategory.xml")
    by_url = connector_for("custom-feed", "https://example.com/feed.xml")
    assert isinstance(by_key, GrantsGovRssConnector)
    assert isinstance(by_url, RssConnector)


def test_connector_factory_selects_grants_gov_rss() -> None:
    connector = connector_for("grants-gov-rss", "https://www.grants.gov/rss/GG_OppModByCategory.xml")
    assert isinstance(connector, GrantsGovRssConnector)


def test_connector_factory_selects_grants_gov_forecast_rss() -> None:
    connector = connector_for("grants-gov-forecast", "https://www.grants.gov/rss/GG_ForecastOpportunities.xml")
    assert isinstance(connector, GrantsGovRssConnector)


def test_connector_factory_selects_nsf_rss_connector() -> None:
    connector = connector_for("nsf-funding-rss", "https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml")
    assert isinstance(connector, NSFFundingRssConnector)


@pytest.mark.asyncio
async def test_fetch_httpx_text_blocks_private_urls() -> None:
    with pytest.raises(ValueError):
        await fetch_httpx_text("http://portal.internal")


def test_allowed_host_helper_rejects_private_domains() -> None:
    assert not is_allowed_host("http://portal.internal", ["portal.internal"])


@pytest.mark.asyncio
async def test_minciencias_connector_parses_listing_fixture() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr>
            <td>976</td>
            <td>
              <a href="/convocatorias/convocatoria-colombia-inteligente-2026">
                CONVOCATORIA COLOMBIA INTELIGENTE 2026
              </a>
            </td>
            <td>
              Fortalecer la investigacion aplicada, el desarrollo tecnologico y la innovacion.
              $749.982.430.291 Martes, Junio 16, 2026
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    connector = MincienciasConnector("https://minciencias.gov.co/convocatorias/todas")
    raw = RawSourceResult(
        source_key="minciencias",
        url="https://minciencias.gov.co/convocatorias/todas",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "CONVOCATORIA COLOMBIA INTELIGENTE 2026"
    assert candidate.entity == "Minciencias"
    assert candidate.country == "Colombia"
    assert candidate.official_url == "https://minciencias.gov.co/convocatorias/convocatoria-colombia-inteligente-2026"
    assert candidate.funding_amount_raw == "$749.982.430.291"
    assert candidate.open_date is not None
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_minciencias_connector_skips_closed_fixture() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr>
            <td>
              <a href="/convocatorias/convocatoria-cerrada-2026">
                CONVOCATORIA CERRADA 2026
              </a>
            </td>
            <td>
              Convocatoria cerrada para investigaci?n aplicada.
              $100.000.000 Martes, Junio 16, 2026
            </td>
          </tr>
          <tr>
            <td>
              <a href="/convocatorias/convocatoria-abierta-2027">
                CONVOCATORIA ABIERTA 2027
              </a>
            </td>
            <td>
              Convocatoria abierta para investigaci?n aplicada.
              $200.000.000 Martes, Junio 16, 2027
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    connector = MincienciasConnector("https://minciencias.gov.co/convocatorias/todas")
    raw = RawSourceResult(
        source_key="minciencias",
        url="https://minciencias.gov.co/convocatorias/todas",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url == "https://minciencias.gov.co/convocatorias/convocatoria-abierta-2027"


@pytest.mark.asyncio
async def test_minciencias_connector_parses_multiple_rows_fixture() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr>
            <td><a href="/convocatorias/call-one">Convocatoria Uno 2026</a></td>
            <td>Texto descriptivo. $10.000.000 15 de junio de 2026</td>
          </tr>
          <tr>
            <td><a href="/convocatorias/call-two">Convocatoria Dos 2026</a></td>
            <td>Otra descripcion. $20.000.000 20 de julio de 2026</td>
          </tr>
        </table>
      </body>
    </html>
    """
    connector = MincienciasConnector("https://minciencias.gov.co/convocatorias/todas")
    raw = RawSourceResult(
        source_key="minciencias",
        url="https://minciencias.gov.co/convocatorias/todas",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url == "https://minciencias.gov.co/convocatorias/call-one"
    assert candidates[1].official_url == "https://minciencias.gov.co/convocatorias/call-two"


def test_connector_factory_selects_minciencias() -> None:
    connector = connector_for("minciencias", "https://minciencias.gov.co/convocatorias/todas")
    assert isinstance(connector, MincienciasConnector)


@pytest.mark.asyncio
async def test_innpulsa_connector_parses_listing_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3>
            <a href="/convocatorias/innpulsa-mujeres">Convocatoria iNNpulsa Mujeres</a>
          </h3>
          <p>
            Abiertas. Programa para fortalecer emprendimientos liderados por mujeres.
            Fecha de cierre: marzo 10, 2027.
            Monto estimado: $120.000.000 COP.
            <a href="/convocatorias/innpulsa-mujeres">Conoce mas</a>
          </p>
        </article>
      </body>
    </html>
    """
    connector = InnpulsaConnector("https://convocatorias.innpulsacolombia.com/api/convocatorias?active_only=true&include_private=false&include_archive=false")
    raw = RawSourceResult(
        source_key="innpulsa",
        url="https://www.innpulsacolombia.com/convocatorias.html",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Convocatoria iNNpulsa Mujeres"
    assert candidate.entity == "iNNpulsa Colombia"
    assert candidate.country == "Colombia"
    assert candidate.official_url == "https://www.innpulsacolombia.com/convocatorias/innpulsa-mujeres"
    assert candidate.summary.startswith("Abiertas.")
    assert candidate.funding_amount_raw == "$120.000.000 COP"
    assert candidate.open_date is not None
    assert (await connector.validate(candidate)).ok

@pytest.mark.asyncio
async def test_innpulsa_connector_skips_closed_listing_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3>
            <a href="/convocatorias/innpulsa-cerrada">Convocatoria iNNpulsa Cerrada</a>
          </h3>
          <p>
            Cerrada. Programa finalizado.
            Fecha de cierre: marzo 10, 2024.
            <a href="/convocatorias/innpulsa-cerrada">Conoce mas</a>
          </p>
        </article>
      </body>
    </html>
    """
    connector = InnpulsaConnector("https://convocatorias.innpulsacolombia.com/api/convocatorias?active_only=true&include_private=false&include_archive=false")
    raw = RawSourceResult(
        source_key="innpulsa",
        url="https://www.innpulsacolombia.com/convocatorias.html",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert candidates == []


def test_connector_factory_selects_innpulsa() -> None:
    connector = connector_for("innpulsa", "https://convocatorias.innpulsacolombia.com/api/convocatorias?active_only=true&include_private=false&include_archive=false")
    assert isinstance(connector, InnpulsaConnector)


@pytest.mark.asyncio
async def test_apc_colombia_connector_parses_teaser_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="page teaser clearfix">
          <h2>
            <a href="/modalidades-de-cooperacion/convocatorias/otras-convocatorias/convocatoria-2026-del-programa-de">
              Convocatoria 2026 del Programa de Cooperación Triangular para América Latina y El Caribe de la Agencia Española de Cooperación Internacional para el Desarrollo (AECID)
            </a>
          </h2>
          <div class="content">
            <p>Convocatoria abierta para proyectos de cooperación triangular. Modificado el 11/04/2027.</p>
          </div>
        </article>
      </body>
    </html>
    """
    connector = ApcColombiaConnector("https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion")
    raw = RawSourceResult(
        source_key="apc-colombia",
        url="https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert "AECID" in candidate.title
    assert candidate.official_url.endswith("/convocatoria-2026-del-programa-de")
    assert candidate.country == "Colombia"
    assert (await connector.validate(candidate)).ok

@pytest.mark.asyncio
async def test_apc_colombia_connector_skips_closed_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="page teaser clearfix">
          <h2><a href="/modalidades-de-cooperacion/convocatorias/convocatoria-cerrada">Convocatoria Cerrada</a></h2>
          <div class="content"><p>Convocatoria cerrada para cooperaci?n. 12/04/2027</p></div>
        </article>
        <article class="page teaser clearfix">
          <h2><a href="/modalidades-de-cooperacion/convocatorias/convocatoria-vigente">Convocatoria Vigente</a></h2>
          <div class="content"><p>Convocatoria abierta para cooperaci?n. 13/04/2027</p></div>
        </article>
      </body>
    </html>
    """
    connector = ApcColombiaConnector("https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion")
    raw = RawSourceResult(
        source_key="apc-colombia",
        url="https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url.endswith("/convocatoria-vigente")


@pytest.mark.asyncio
async def test_apc_colombia_connector_parses_multiple_cards_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="page teaser clearfix">
          <h2><a href="/modalidades-de-cooperacion/convocatorias/convocatoria-uno">Convocatoria Uno</a></h2>
          <div class="content"><p>Convocatoria abierta. 11/04/2027</p></div>
        </article>
        <article class="page teaser clearfix">
          <h2><a href="/modalidades-de-cooperacion/convocatorias/convocatoria-dos">Convocatoria Dos</a></h2>
          <div class="content"><p>Convocatoria abierta para cooperacion. 12/04/2027</p></div>
        </article>
      </body>
    </html>
    """
    connector = ApcColombiaConnector("https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion")
    raw = RawSourceResult(
        source_key="apc-colombia",
        url="https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url.endswith("/convocatoria-uno")
    assert candidates[1].official_url.endswith("/convocatoria-dos")


def test_connector_factory_selects_apc_and_eu() -> None:
    apc = connector_for("apc-colombia", "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion")
    eu = connector_for("eu-funding-tenders", "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals")
    assert isinstance(apc, ApcColombiaConnector)
    assert isinstance(eu, EuFundingTendersConnector)


@pytest.mark.asyncio
async def test_eu_connector_parses_search_api_fixture() -> None:
    payload = {
        "results": [
            {
                "reference": "2026-open-call",
                "summary": "Open Horizons Open Call #3",
                "metadata": {
                    "callTitle": ["Open Horizons Open Call #3"],
                    "identifier": ["OH-2026-03"],
                    "callIdentifier": ["OH-2026-03"],
                    "status": ["31094501"],
                    "startDate": ["2026-05-01T00:00:00.000+0000"],
                    "deadlineDate": ["2026-12-01T00:00:00.000+0000"],
                    "keywords": ["innovation", "open call"],
                    "actions": [
                        json.dumps(
                            [
                                {
                                    "plannedOpeningDate": "01 May 2026",
                                    "deadlineDates": ["01 December 2026"],
                                    "status": {"id": 31094501, "abbreviation": "Open", "description": "Open"},
                                }
                            ]
                        )
                    ],
                },
            }
        ]
    }
    connector = EuFundingTendersConnector("https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals")
    raw = RawSourceResult(
        source_key="eu-funding-tenders",
        url="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals",
        content=json.dumps(payload),
        content_type="application/json",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Open Horizons Open Call #3"
    assert candidate.official_url.endswith("/OH-2026-03")
    assert candidate.country == "European Union"
    assert candidate.open_date is not None
    assert candidate.close_date is not None
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_eu_connector_parses_multiple_results_fixture() -> None:
    payload = {
        "results": [
            {
                "reference": "2026-open-call-a",
                "summary": "Open Horizons Open Call A",
                "metadata": {
                    "callTitle": ["Open Horizons Open Call A"],
                    "identifier": ["OH-2026-A"],
                    "status": ["31094501"],
                    "startDate": ["2026-05-01T00:00:00.000+0000"],
                    "deadlineDate": ["2026-12-01T00:00:00.000+0000"],
                    "keywords": ["innovation"],
                },
            },
            {
                "reference": "2026-open-call-b",
                "summary": "Open Horizons Open Call B",
                "metadata": {
                    "callTitle": ["Open Horizons Open Call B"],
                    "identifier": ["OH-2026-B"],
                    "status": ["31094501"],
                    "startDate": ["2026-05-01T00:00:00.000+0000"],
                    "deadlineDate": ["2026-12-01T00:00:00.000+0000"],
                    "keywords": ["research"],
                },
            },
        ]
    }
    connector = EuFundingTendersConnector("https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals")
    raw = RawSourceResult(
        source_key="eu-funding-tenders",
        url="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals",
        content=json.dumps(payload),
        content_type="application/json",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url.endswith("/OH-2026-A")
    assert candidates[1].official_url.endswith("/OH-2026-B")


@pytest.mark.asyncio
async def test_simpler_grants_connector_parses_search_fixture() -> None:
    html = r"""
    <script>self.__next_f.push([1,"
    {\"href\":\"/opportunity/21f5b3ac-4760-44be-a577-936e8915ea57\",\"id\":\"search-result-link-1-1\",\"children\":\"Public Diplomacy Section Praia: Small Grants Program\"}
    {\"children\":[\"Number\",\":\"]}],\" \",\"PAS-PRAIA-FY26-01\"}
    {\"children\":\"Agency\"}],\"children\":\"U.S. Mission to Cabo Verde\"}
    {\"children\":\"Close date\"}],\" \",\"Jul 1, 2026\"}
    {\"children\":\"Posted date\"}],\" \",\"Jun 1, 2026\"}
    "</script>
    """
    connector = SimplerGrantsConnector("https://simpler.grants.gov/search")
    raw = RawSourceResult(
        source_key="simpler-grants",
        url="https://simpler.grants.gov/search",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Public Diplomacy Section Praia: Small Grants Program"
    assert candidate.country == "United States"
    assert candidate.official_url == "https://simpler.grants.gov/opportunity/21f5b3ac-4760-44be-a577-936e8915ea57"
    assert "PAS-PRAIA-FY26-01" in candidate.summary
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_nsf_connector_parses_multiple_cards_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/awardsearch/showAward?AWD_ID=123">NSF Research Opportunity 2026</a></h3>
          <p>Funding opportunity for innovative research proposals. Closing date March 10, 2027.</p>
        </article>
        <article class="card">
          <h3><a href="/awardsearch/showAward?AWD_ID=456">NSF AI Education Grant</a></h3>
          <p>Funding opportunity for education and AI capacity building. Closing date April 20, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = NSFFundingConnector("https://www.nsf.gov/funding")
    raw = RawSourceResult(
        source_key="nsf-funding",
        url="https://www.nsf.gov/funding",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url == "https://www.nsf.gov/awardsearch/showAward?AWD_ID=123"
    assert candidates[1].official_url == "https://www.nsf.gov/awardsearch/showAward?AWD_ID=456"


def test_connector_factory_selects_simpler_grants() -> None:
    connector = connector_for("simpler-grants", "https://simpler.grants.gov/search")
    assert isinstance(connector, SimplerGrantsConnector)


@pytest.mark.asyncio
async def test_unwomen_connector_parses_listing_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/en/how-we-work/innovation-and-technology/open-call-2026">Open Call 2026</a></h3>
          <p>UN Women innovation challenge for women-led digital solutions. Deadline March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = UnwomenInnovateConnector("https://www.unwomen.org/en/how-we-work/innovation-and-technology")
    raw = RawSourceResult(
        source_key="unwomen-innovate",
        url="https://www.unwomen.org/en/how-we-work/innovation-and-technology",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.entity == "UN Women"
    assert candidate.country == "International"
    assert candidate.official_url == "https://www.unwomen.org/en/how-we-work/innovation-and-technology/open-call-2026"
    assert "innovation" in candidate.categories
    assert candidate.close_date is not None
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_unwomen_connector_parses_multiple_cards_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/en/how-we-work/innovation-and-technology/closed-call-2024">Closed Call 2024</a></h3>
          <p>UN Women innovation challenge for women-led digital solutions. This call is closed. Deadline March 10, 2024.</p>
        </article>
        <article class="card">
          <h3><a href="/en/how-we-work/innovation-and-technology/open-call-2027">Open Call 2027</a></h3>
          <p>UN Women innovation challenge for women-led digital solutions. Deadline March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = UnwomenInnovateConnector("https://www.unwomen.org/en/how-we-work/innovation-and-technology")
    raw = RawSourceResult(
        source_key="unwomen-innovate",
        url="https://www.unwomen.org/en/how-we-work/innovation-and-technology",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url.endswith("/open-call-2027")


@pytest.mark.asyncio
async def test_unwomen_connector_skips_closed_calls() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/en/how-we-work/innovation-and-technology/closed-call-2024">Closed Call 2024</a></h3>
          <p>UN Women innovation challenge for women-led digital solutions. This call is closed. Deadline March 10, 2024.</p>
        </article>
        <article class="card">
          <h3><a href="/en/how-we-work/innovation-and-technology/open-call-2027">Open Call 2027</a></h3>
          <p>UN Women innovation challenge for women-led digital solutions. Deadline March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = UnwomenInnovateConnector("https://www.unwomen.org/en/how-we-work/innovation-and-technology")
    raw = RawSourceResult(
        source_key="unwomen-innovate",
        url="https://www.unwomen.org/en/how-we-work/innovation-and-technology",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url.endswith("/open-call-2027")


@pytest.mark.asyncio
async def test_generic_html_connector_parses_bento_card_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/calls/open-call-2026">Open Call 2026</a></h3>
          <p>Funding for research and innovation projects. Deadline March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = GenericHtmlConnector("generic-html", "https://example.org/calls")
    raw = RawSourceResult(
        source_key="generic-html",
        url="https://example.org/calls",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Open Call 2026"
    assert candidate.official_url == "https://example.org/calls/open-call-2026"
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_generic_html_connector_skips_closed_calls() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/calls/closed-call-2024">Closed Call 2024</a></h3>
          <p>This call is closed. Deadline March 10, 2024.</p>
        </article>
        <article class="card">
          <h3><a href="/calls/open-call-2027">Open Call 2027</a></h3>
          <p>Funding for research and innovation projects. Deadline March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = GenericHtmlConnector("generic-html", "https://example.org/calls")
    raw = RawSourceResult(
        source_key="generic-html",
        url="https://example.org/calls",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url == "https://example.org/calls/open-call-2027"


@pytest.mark.asyncio
async def test_generic_html_connector_skips_css_noise_cards() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/calls/noise">a { color: white; } .box-address { display: flex; }</a></h3>
          <p>.caja1:hover, .caja2:hover { border: white 10px double; }</p>
        </article>
        <article class="card">
          <h3><a href="/calls/open-call-2027">Open Call 2027</a></h3>
          <p>Funding for research and innovation projects. Deadline March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = GenericHtmlConnector("generic-html", "https://example.org/calls")
    raw = RawSourceResult(
        source_key="generic-html",
        url="https://example.org/calls",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url == "https://example.org/calls/open-call-2027"


@pytest.mark.asyncio
async def test_generic_html_connector_parses_opportunity_card_fixture() -> None:
    html = """
    <html>
      <body>
        <div class="opportunity-card">
          <a href="/opportunity/ukri-research-call-2026">UKRI Research Opportunity 2026</a>
          <p>Open for applications. Funding for interdisciplinary research proposals.</p>
        </div>
      </body>
    </html>
    """
    connector = GenericHtmlConnector("ukri-opportunities", "https://www.ukri.org/opportunity/")
    raw = RawSourceResult(
        source_key="ukri-opportunities",
        url="https://www.ukri.org/opportunity/",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "UKRI Research Opportunity 2026"
    assert candidate.official_url == "https://www.ukri.org/opportunity/ukri-research-call-2026"
    assert "opportunity" in candidate.summary.lower()
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_generic_html_connector_parses_ld_json_fixture() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
              {
                "@type": "ListItem",
                "name": "Innovation Grant 2026",
                "url": "/calls/innovation-grant-2026",
                "description": "Funding for innovation projects"
              }
            ]
          }
        </script>
      </head>
      <body></body>
    </html>
    """
    connector = GenericHtmlConnector("generic-html", "https://example.org/calls")
    raw = RawSourceResult(
        source_key="generic-html",
        url="https://example.org/calls",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].title == "Innovation Grant 2026"
    assert candidates[0].official_url == "https://example.org/calls/innovation-grant-2026"


@pytest.mark.asyncio
async def test_generic_html_connector_parses_next_data_fixture() -> None:
    html = """
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
          {
            "props": {
              "pageProps": {
                "items": [
                  {
                    "title": "Next.js Funding Call 2026",
                    "url": "/calls/nextjs-funding-call-2026",
                    "description": "Funding for digital transformation and innovation.",
                    "country": "Colombia",
                    "categories": ["innovation", "grants"]
                  }
                ]
              }
            }
          }
        </script>
      </head>
      <body></body>
    </html>
    """
    connector = GenericHtmlConnector("generic-html", "https://example.org/calls")
    raw = RawSourceResult(
        source_key="generic-html",
        url="https://example.org/calls",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].title == "Next.js Funding Call 2026"
    assert candidates[0].official_url == "https://example.org/calls/nextjs-funding-call-2026"
    assert "innovation" in candidates[0].categories


@pytest.mark.asyncio
async def test_icetex_connector_parses_vigentes_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/es/-/icetex-abre-convocatoria-150-becas-30-maestrias-presenciales-en-espana-con-universidad-antonio-nebrija">
            ICETEX abre convocatoria de 150 becas del 30 % para maestrías presenciales en España
          </a></h3>
          <p>Convocatoria abierta hasta el 20 de mayo de 2026. País: España.</p>
        </article>
        <article class="card">
          <h3><a href="/es/-/icetex-universidad-europea-lanzan-mas-20-oportunidades-beca-maestrias-virtuales">
            ICETEX y la Universidad Europea lanzan más de 20 oportunidades de beca para maestrías virtuales
          </a></h3>
          <p>País: Estados Unidos. Cierre 2026-06-30.</p>
        </article>
      </body>
    </html>
    """
    connector = IcetexConnector("https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes")
    raw = RawSourceResult(
        source_key="icetex-vigentes",
        url="https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].country in {"Spain", "Colombia"}
    assert candidates[1].official_url.startswith("https://web.icetex.gov.co/")
    assert (await connector.validate(candidates[0])).ok


@pytest.mark.asyncio
async def test_icetex_connector_parses_multiple_cards_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/es/-/beca-uno">Beca Uno para maestria en Espana</a></h3>
          <p>Convocatoria abierta hasta 2026-05-20.</p>
        </article>
        <article class="card">
          <h3><a href="/es/-/beca-dos">Beca Dos para doctorado en Estados Unidos</a></h3>
          <p>Convocatoria abierta hasta 2026-06-30.</p>
        </article>
      </body>
    </html>
    """
    connector = IcetexConnector("https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes")
    raw = RawSourceResult(
        source_key="icetex-vigentes",
        url="https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url == "https://web.icetex.gov.co/es/-/beca-uno"
    assert candidates[1].official_url == "https://web.icetex.gov.co/es/-/beca-dos"


@pytest.mark.asyncio
async def test_mineducacion_connector_parses_becas_fixture() -> None:
    html = """
    <html>
      <body>
        <section>
          <h2>Convocatoria 2026 - Programa de Cooperación Triangular para América Latina y El Caribe</h2>
          <p>Cooperante: AECID. Fecha límite 6 de julio de 2026. Postulación para entidades públicas y universidades.</p>
        </section>
        <section>
          <h2>BECAS ICETEX (abril-mayo 2026)</h2>
          <p>Listado de becas vigentes para maestrías y doctorados en España y Estados Unidos.</p>
        </section>
      </body>
    </html>
    """
    connector = MineducacionConnector(
        "https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias"
    )
    raw = RawSourceResult(
        source_key="mineducacion-becas",
        url="https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].country in {"International", "Colombia"}
    assert candidates[1].official_url.startswith("https://www.mineducacion.gov.co/")
    assert (await connector.validate(candidates[0])).ok


@pytest.mark.asyncio
async def test_mineducacion_connector_parses_multiple_sections_fixture() -> None:
    html = """
    <html>
      <body>
        <section>
          <h2><a href="/portal/convocatoria-uno">Convocatoria Uno 2026</a></h2>
          <p>Fecha limite 6 de julio de 2026.</p>
        </section>
        <section>
          <h2><a href="/portal/convocatoria-dos">Beca Dos 2026</a></h2>
          <p>Programa de cooperacion internacional.</p>
        </section>
      </body>
    </html>
    """
    connector = MineducacionConnector(
        "https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias"
    )
    raw = RawSourceResult(
        source_key="mineducacion-becas",
        url="https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url == "https://www.mineducacion.gov.co/portal/convocatoria-uno"
    assert candidates[1].official_url == "https://www.mineducacion.gov.co/portal/convocatoria-dos"


@pytest.mark.asyncio
async def test_innovamos_and_undef_connectors_parse_fixture() -> None:
    innovamos_html = """
    <html>
      <body>
        <h1>Convocatoria Subvenciones a proyectos en alianza con Global Innovation Fund</h1>
        <p>A través de esta convocatoria invitamos a innovadores e investigadores de todo el mundo a solicitar subvenciones.</p>
      </body>
    </html>
    """
    undef_html = """
    <html>
      <body>
        <h1>Applying for an UNDEF Project Grant</h1>
        <p>UNDEF accepts proposals during its annual funding window.</p>
      </body>
    </html>
    """
    innovamos = InnovamosConnector("innovamos-global-innovation-fund", "https://www.innovamos.gov.co/instrumentos/convocatoria-subvenciones-a-proyectos-en-alianza-con")
    undef = UNDEFConnector("https://www.un.org/democracyfund/en/apply-for-funding")
    innovamos_raw = RawSourceResult(
        source_key="innovamos-global-innovation-fund",
        url="https://www.innovamos.gov.co/instrumentos/convocatoria-subvenciones-a-proyectos-en-alianza-con",
        content=innovamos_html,
        content_type="text/html",
    )
    undef_raw = RawSourceResult(
        source_key="undef",
        url="https://www.un.org/democracyfund/en/apply-for-funding",
        content=undef_html,
        content_type="text/html",
    )

    innovamos_candidates = await innovamos.parse(innovamos_raw)
    undef_candidates = await undef.parse(undef_raw)

    assert len(innovamos_candidates) == 1
    assert innovamos_candidates[0].country == "Colombia"
    assert (await innovamos.validate(innovamos_candidates[0])).ok
    assert len(undef_candidates) == 1
    assert undef_candidates[0].country == "International"
    assert (await undef.validate(undef_candidates[0])).ok


@pytest.mark.asyncio
async def test_innovamos_connector_parses_multiple_cards_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/instrumentos/call-one">Convocatoria Innovamos Uno</a></h3>
          <p>Subvencion para alianzas de innovacion y sostenibilidad. Cierre 2026-08-10.</p>
        </article>
        <article class="card">
          <h3><a href="/instrumentos/call-two">Fondo Innovamos Dos</a></h3>
          <p>Funding for research and innovation partnerships. Deadline September 15, 2026.</p>
        </article>
      </body>
    </html>
    """
    connector = InnovamosConnector(
        "innovamos-global-innovation-fund",
        "https://www.innovamos.gov.co/instrumentos/convocatoria-subvenciones-a-proyectos-en-alianza-con",
    )
    raw = RawSourceResult(
        source_key="innovamos-global-innovation-fund",
        url="https://www.innovamos.gov.co/instrumentos/convocatoria-subvenciones-a-proyectos-en-alianza-con",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url == "https://www.innovamos.gov.co/instrumentos/call-one"
    assert candidates[1].official_url == "https://www.innovamos.gov.co/instrumentos/call-two"
    assert candidates[0].country == "Colombia"
    assert candidates[1].country == "Colombia"


@pytest.mark.asyncio
async def test_undef_connector_parses_multiple_call_fixture() -> None:
    html = """
    <html>
      <body>
        <section class="teaser">
          <h2><a href="/democracyfund/en/apply-for-funding/project-a">Project A Call</a></h2>
          <p>UNDEF call for proposals, deadline April 8, 2026.</p>
        </section>
        <section class="teaser">
          <h2><a href="/democracyfund/en/apply-for-funding/project-b">Project B Grant</a></h2>
          <p>UNDEF funding opportunity for civic participation.</p>
        </section>
      </body>
    </html>
    """
    connector = UNDEFConnector("https://www.un.org/democracyfund/en/apply-for-funding")
    raw = RawSourceResult(
        source_key="undef",
        url="https://www.un.org/democracyfund/en/apply-for-funding",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 2
    assert candidates[0].official_url == "https://www.un.org/democracyfund/en/apply-for-funding/project-a"
    assert candidates[1].official_url == "https://www.un.org/democracyfund/en/apply-for-funding/project-b"
    assert candidates[0].entity == "United Nations Democracy Fund"


@pytest.mark.asyncio
async def test_nsf_connector_parses_fixture() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/awardsearch/showAward?AWD_ID=123">NSF Research Opportunity 2026</a></h3>
          <p>Funding opportunity for innovative research proposals. Closing date March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = NSFFundingConnector("https://www.nsf.gov/funding")
    raw = RawSourceResult(
        source_key="nsf-funding",
        url="https://www.nsf.gov/funding",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.entity == "National Science Foundation"
    assert candidate.country == "United States"
    assert candidate.official_url == "https://www.nsf.gov/awardsearch/showAward?AWD_ID=123"
    assert candidate.open_date is not None or candidate.close_date is not None
    assert (await connector.validate(candidate)).ok


@pytest.mark.asyncio
async def test_nsf_connector_skips_closed_calls() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/awardsearch/showAward?AWD_ID=999">NSF Archived Research Opportunity</a></h3>
          <p>This solicitation is closed and archived. Closing date March 10, 2024.</p>
        </article>
        <article class="card">
          <h3><a href="/awardsearch/showAward?AWD_ID=1000">NSF Open Research Opportunity</a></h3>
          <p>Funding opportunity for innovative research proposals. Closing date March 10, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = NSFFundingConnector("https://www.nsf.gov/funding")
    raw = RawSourceResult(
        source_key="nsf-funding",
        url="https://www.nsf.gov/funding",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url == "https://www.nsf.gov/awardsearch/showAward?AWD_ID=1000"


@pytest.mark.asyncio
async def test_nsf_rss_connector_parses_fixture() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>NSF Funding Opportunities</title>
        <item>
          <title>NSF Research and Innovation Seed Grant</title>
          <link>https://www.nsf.gov/funding/opportunity/seed-grant</link>
          <description><![CDATA[Funding for innovative research proposals. Closing date March 10, 2026.]]></description>
          <category>Research</category>
          <pubDate>Fri, 19 Jun 2026 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    connector = NSFFundingRssConnector("nsf-funding-rss", "https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml")
    raw = RawSourceResult(
        source_key="nsf-funding-rss",
        url="https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml",
        content=xml,
        content_type="application/rss+xml",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.entity == "National Science Foundation"
    assert candidate.country == "United States"
    assert candidate.official_url == "https://www.nsf.gov/funding/opportunity/seed-grant"
    assert "research" in candidate.categories


@pytest.mark.asyncio
async def test_ukri_and_unesco_connectors_parse_fixture() -> None:
    ukri_html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/opportunity/ukri-research-call">UKRI Research Call 2026</a></h3>
          <p>Funding opportunity for collaborative research proposals. Closes 12 March 2026.</p>
        </article>
      </body>
    </html>
    """
    unesco_html = """
    <html>
      <body>
        <article>
          <h1><a href="/en/articles/call-proposals-2027">UNESCO Call for Proposals 2027</a></h1>
          <p>International call for proposals. Deadline April 8, 2027.</p>
        </article>
      </body>
    </html>
    """
    ukri = UKRIConnector("https://www.ukri.org/opportunity/")
    unesco = UNESCOConnector("https://www.unesco.org/en/articles/call-proposals")
    ukri_raw = RawSourceResult(
        source_key="ukri-opportunities",
        url="https://www.ukri.org/opportunity/",
        content=ukri_html,
        content_type="text/html",
    )
    unesco_raw = RawSourceResult(
        source_key="unesco-call-for-proposals",
        url="https://www.unesco.org/en/articles/call-proposals",
        content=unesco_html,
        content_type="text/html",
    )

    ukri_candidates = await ukri.parse(ukri_raw)
    unesco_candidates = await unesco.parse(unesco_raw)

    assert len(ukri_candidates) == 1
    assert ukri_candidates[0].country == "United Kingdom"
    assert (await ukri.validate(ukri_candidates[0])).ok
    assert len(unesco_candidates) == 1
    assert unesco_candidates[0].country == "International"
    assert (await unesco.validate(unesco_candidates[0])).ok


@pytest.mark.asyncio
async def test_ukri_and_unesco_multiple_results_fixture() -> None:
    ukri_html = """
    <html>
      <body>
        <article class="card">
          <h3><a href="/opportunity/ukri-research-call">UKRI Research Call 2026</a></h3>
          <p>Funding opportunity for collaborative research proposals. Closes 12 March 2026.</p>
        </article>
        <article class="card">
          <h3><a href="/opportunity/ukri-innovation-call">UKRI Innovation Call 2026</a></h3>
          <p>Competition for innovative solutions. Closes 20 April 2026.</p>
        </article>
      </body>
    </html>
    """
    unesco_html = """
    <html>
      <body>
        <article>
          <h1><a href="/en/articles/call-proposals-2027">UNESCO Call for Proposals 2027</a></h1>
          <p>International call for proposals. Deadline April 8, 2027.</p>
        </article>
        <article>
          <h1><a href="/en/articles/call-proposals-2028">UNESCO Call for Proposals 2028</a></h1>
          <p>International call for proposals. Deadline May 8, 2028.</p>
        </article>
      </body>
    </html>
    """
    ukri = UKRIConnector("https://www.ukri.org/opportunity/")
    unesco = UNESCOConnector("https://www.unesco.org/en/articles/call-proposals")
    ukri_raw = RawSourceResult(
        source_key="ukri-opportunities",
        url="https://www.ukri.org/opportunity/",
        content=ukri_html,
        content_type="text/html",
    )
    unesco_raw = RawSourceResult(
        source_key="unesco-call-for-proposals",
        url="https://www.unesco.org/en/articles/call-proposals",
        content=unesco_html,
        content_type="text/html",
    )

    ukri_candidates = await ukri.parse(ukri_raw)
    unesco_candidates = await unesco.parse(unesco_raw)

    assert len(ukri_candidates) == 2
    assert ukri_candidates[0].official_url.endswith("/ukri-research-call")
    assert ukri_candidates[1].official_url.endswith("/ukri-innovation-call")
    assert len(unesco_candidates) == 2
    assert unesco_candidates[0].official_url.endswith("/call-proposals-2027")
    assert unesco_candidates[1].official_url.endswith("/call-proposals-2028")


@pytest.mark.asyncio
async def test_unesco_connector_skips_closed_calls() -> None:
    html = """
    <html>
      <body>
        <article>
          <h1><a href="/en/articles/closed-call-2024">UNESCO Closed Call 2024</a></h1>
          <p>International call for proposals. Deadline April 8, 2024.</p>
        </article>
        <article>
          <h1><a href="/en/articles/open-call-2027">UNESCO Open Call 2027</a></h1>
          <p>International call for proposals. Deadline May 8, 2027.</p>
        </article>
      </body>
    </html>
    """
    connector = UNESCOConnector("https://www.unesco.org/en/articles/call-proposals")
    raw = RawSourceResult(
        source_key="unesco-call-for-proposals",
        url="https://www.unesco.org/en/articles/call-proposals",
        content=html,
        content_type="text/html",
    )

    candidates = await connector.parse(raw)

    assert len(candidates) == 1
    assert candidates[0].official_url.endswith("/open-call-2027")
