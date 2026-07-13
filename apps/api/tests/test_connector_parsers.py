"""Tests de parse() para conectores con logica de fetch compleja.

Cada conector se testea inyectando RawSourceResult directamente,
sin mockear fetch_httpx_text. Esto permite probar la logica de
parseo aisladamente.
"""
from __future__ import annotations

import json

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult


def _raw(content: str, content_type: str = "application/json") -> RawSourceResult:
    return RawSourceResult(
        source_key="test",
        url="http://example.com",
        content=content,
        content_type=content_type,
    )


class TestEuFundingTendersParse:
    """Espera {"results": [...]} con metadata.callTitle / identifier."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.eu_funding_tenders import EuFundingTendersConnector

        connector = EuFundingTendersConnector()
        data = {
            "results": [
                {
                    "metadata": {
                        "callTitle": ["Horizon Europe Cluster 6 Call"],
                        "identifier": ["HORIZON-CL6-2027"],
                        "callIdentifier": ["HORIZON-CL6-2027"],
                        "status": ["31094501"],
                        "actions": [
                            {
                                "plannedOpeningDate": "2026-12-01T00:00:00Z",
                                "deadlineDates": ["2027-06-30T00:00:00Z"],
                            }
                        ],
                    }
                }
            ]
        }
        raw = _raw(json.dumps(data))
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "Horizon Europe" in candidates[0].title

    @pytest.mark.asyncio
    async def test_parse_skips_closed(self):
        from app.connectors.eu_funding_tenders import EuFundingTendersConnector

        connector = EuFundingTendersConnector()
        data = {
            "results": [
                {
                    "metadata": {
                        "callTitle": ["Closed Call"],
                        "identifier": ["CLOSED-001"],
                        "callIdentifier": ["CLOSED-001"],
                        "status": ["31094503"],
                    }
                }
            ]
        }
        raw = _raw(json.dumps(data))
        candidates = await connector.parse(raw)
        assert len(candidates) == 0


class TestEicAcceleratorParse:
    """Misma estructura que EU Funding Tenders (SEDIA API)."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.eic_accelerator import EicAcceleratorConnector

        connector = EicAcceleratorConnector()
        data = {
            "results": [
                {
                    "metadata": {
                        "callTitle": ["EIC Accelerator Open 2027"],
                        "identifier": ["EIC-2027-ACCEL"],
                        "callIdentifier": ["EIC-2027-ACCEL"],
                        "status": ["31094501"],
                        "actions": [
                            {
                                "plannedOpeningDate": "2027-01-01T00:00:00Z",
                                "deadlineDates": ["2027-06-15T00:00:00Z"],
                            }
                        ],
                    }
                }
            ]
        }
        raw = _raw(json.dumps(data))
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "EIC" in candidates[0].title

    @pytest.mark.asyncio
    async def test_parse_skips_without_identifier(self):
        from app.connectors.eic_accelerator import EicAcceleratorConnector

        connector = EicAcceleratorConnector()
        data = {"results": [{"metadata": {"callTitle": ["No ID Call"]}}]}
        raw = _raw(json.dumps(data))
        candidates = await connector.parse(raw)
        assert len(candidates) == 0


class TestHorizonSediaParse:
    """Misma estructura SEDIA (metadata.callTitle + identifier)."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.horizon_sedia import HorizonSediaConnector

        connector = HorizonSediaConnector()
        data = {
            "results": [
                {
                    "metadata": {
                        "callTitle": ["MSCA Postdoctoral Fellowships 2027"],
                        "identifier": ["MSCA-PF-2027"],
                        "callIdentifier": ["MSCA-PF-2027"],
                        "status": ["31094501"],
                        "actions": [
                            {
                                "plannedOpeningDate": "2027-04-01T00:00:00Z",
                                "deadlineDates": ["2027-09-15T00:00:00Z"],
                            }
                        ],
                    }
                }
            ]
        }
        raw = _raw(json.dumps(data))
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "MSCA" in candidates[0].title


class TestWellcomeParse:
    """Espera HTML con __NEXT_DATA__ script -> props.pageProps.initialListings."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.wellcome import WellcomeConnector

        connector = WellcomeConnector()
        html = f"""<html><body>
        <script id="__NEXT_DATA__" type="application/json">
        {json.dumps({"props": {"pageProps": {"initialListings": [
            {"title": "Early-Career Awards 2027", "url": "/funding/eca-2027",
             "scheme_status": "open", "scheme_closes_for_applications": "1 June 2027"}
        ]}}})}
        </script></body></html>"""
        raw = RawSourceResult(
            source_key="wellcome-grants",
            url="https://wellcome.org/grants",
            content=html,
            content_type="text/html",
        )
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "Early-Career" in candidates[0].title


# SimplerGrantsParse omitido: usa regex sobre formato API especifico
# que requiere datos reales del endpoint. Se testea via test_simpler_grants.py.


class TestGlobalInnovationFundParse:
    """Global Innovation Fund parsea HTML."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.global_innovation_fund import GlobalInnovationFundConnector

        connector = GlobalInnovationFundConnector()
        html = """<html><body>
            <article>
                <h2><a href="/apply/gif-2027">Global Innovation Fund 2027</a></h2>
                <p>Funding for social innovation</p>
            </article>
        </body></html>"""
        raw = RawSourceResult("test", "https://globalinnovation.fund", html, "text/html")
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "Global Innovation Fund" in candidates[0].title


class TestIdrcFundingParse:
    """IDRC parsea HTML."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.idrc_funding import IdrcFundingConnector

        connector = IdrcFundingConnector()
        html = """<html><body>
            <div class="funding-opportunity">
                <h3><a href="/en/funding/idrc-research-grant-2027">IDRC Research Grant 2027 — Call for Proposals</a></h3>
                <p>Deadline: 2027-10-30</p>
            </div>
        </body></html>"""
        raw = RawSourceResult("test", "https://idrc-crdi.ca/funding", html, "text/html")
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "IDRC" in candidates[0].title


class TestUnwomenParse:
    """UN Women parsea HTML."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.unwomen_innovate import UnwomenInnovateConnector

        connector = UnwomenInnovateConnector()
        html = """<html><body>
            <div class="call">
                <h3><a href="/call/2027/gender-equality">UN Women Innovation Call 2027</a></h3>
                <p>Deadline: 2027-09-15</p>
            </div>
        </body></html>"""
        raw = RawSourceResult("test", "https://www.unwomen.org", html, "text/html")
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "UN Women" in candidates[0].title


class TestUnescoParse:
    """UNESCO parsea HTML."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.unesco import UNESCOConnector

        connector = UNESCOConnector()
        html = """<html><body>
            <div class="call">
                <h3><a href="/call/2027/001">UNESCO Call for Proposals 2027</a></h3>
                <p>Deadline: 2027-10-01</p>
            </div>
        </body></html>"""
        raw = RawSourceResult(
            source_key="unesco-call-for-proposals",
            url="https://unesco.org/calls",
            content=html,
            content_type="text/html",
        )
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "UNESCO" in candidates[0].title


class TestAniiUruguayParse:
    """ANII Uruguay parsea HTML con separador <!-- page: -->."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.anii_uruguay import AniiUruguayConnector

        connector = AniiUruguayConnector()
        html = """<html><body>
<!-- page: https://www.anii.org.uy/apoyos/innovacion/2027/fondo-sectorial -->
<div class="convocatoria">
    <h3><a href="https://www.anii.org.uy/apoyos/innovacion/2027/fondo-sectorial">ANII Fondo Sectorial 2027</a></h3>
    <p>Deadline: 2027-12-01</p>
</div>
</body></html>"""
        raw = RawSourceResult("test", "https://www.anii.org.uy/convocatorias", html, "text/html")
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "ANII" in candidates[0].title


class TestApcColombiaParse:
    """APC Colombia parsea HTML con metadata de paginas."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.apc_colombia import ApcColombiaConnector

        connector = ApcColombiaConnector()
        html = """<html><body>
<div class="convocatoria">
    <h3><a href="https://www.apccolombia.gov.co/convocatoria/cooperacion-2027">Convocatoria Cooperacion APC 2027</a></h3>
    <p>Deadline: 2027-11-15</p>
</div>
</body></html>"""
        raw = RawSourceResult(
            "test", "https://www.apccolombia.gov.co/seccion/convocatorias", html, "text/html",
            metadata={
                "pages": [
                    {
                        "url": "https://www.apccolombia.gov.co/seccion/convocatorias",
                        "content": """<html><body>
<div class="convocatoria">
    <h3><a href="https://www.apccolombia.gov.co/convocatoria/cooperacion-2027">Convocatoria Cooperacion APC 2027</a></h3>
    <p>Deadline: 2027-11-15</p>
</div>
</body></html>""",
                    }
                ]
            },
        )
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "APC" in candidates[0].title


class TestUnwomenParse:
    """UN Women parsea HTML."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.unwomen_innovate import UnwomenInnovateConnector

        connector = UnwomenInnovateConnector()
        html = """<html><body>
            <div class="call">
                <h3><a href="/call/2027/gender-equality">UN Women Innovation Call 2027</a></h3>
                <p>Deadline: 2027-09-15</p>
            </div>
        </body></html>"""
        raw = RawSourceResult("test", "https://www.unwomen.org", html, "text/html")
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "UN Women" in candidates[0].title


class TestUnescoParse:
    """UNESCO parsea HTML."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.unesco import UNESCOConnector

        connector = UNESCOConnector()
        html = """<html><body>
            <div class="call">
                <h3><a href="/call/2027/001">UNESCO Call for Proposals 2027</a></h3>
                <p>Deadline: 2027-10-01</p>
            </div>
        </body></html>"""
        raw = RawSourceResult(
            source_key="unesco-call-for-proposals",
            url="https://unesco.org/calls",
            content=html,
            content_type="text/html",
        )
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "UNESCO" in candidates[0].title


class TestAniiUruguayParse:
    """ANII Uruguay parsea HTML con separador <!-- page: -->."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.anii_uruguay import AniiUruguayConnector

        connector = AniiUruguayConnector()
        html = """<html><body>
<!-- page: https://www.anii.org.uy/apoyos/innovacion/2027/fondo-sectorial -->
<div class="convocatoria">
    <h3><a href="https://www.anii.org.uy/apoyos/innovacion/2027/fondo-sectorial">ANII Fondo Sectorial 2027</a></h3>
    <p>Deadline: 2027-12-01</p>
</div>
</body></html>"""
        raw = RawSourceResult("test", "https://www.anii.org.uy/convocatorias", html, "text/html")
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "ANII" in candidates[0].title


class TestApcColombiaParse:
    """APC Colombia parsea HTML con metadata de paginas."""

    @pytest.mark.asyncio
    async def test_parse_yields_candidate(self):
        from app.connectors.apc_colombia import ApcColombiaConnector

        connector = ApcColombiaConnector()
        html = """<html><body>
<div class="convocatoria">
    <h3><a href="https://www.apccolombia.gov.co/convocatoria/cooperacion-2027">Convocatoria Cooperacion APC 2027</a></h3>
    <p>Deadline: 2027-11-15</p>
</div>
</body></html>"""
        raw = RawSourceResult(
            "test", "https://www.apccolombia.gov.co/seccion/convocatorias", html, "text/html",
            metadata={
                "pages": [
                    {
                        "url": "https://www.apccolombia.gov.co/seccion/convocatorias",
                        "content": """<html><body>
<div class="convocatoria">
    <h3><a href="https://www.apccolombia.gov.co/convocatoria/cooperacion-2027">Convocatoria Cooperacion APC 2027</a></h3>
    <p>Deadline: 2027-11-15</p>
</div>
</body></html>""",
                    }
                ]
            },
        )
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        assert "APC" in candidates[0].title


