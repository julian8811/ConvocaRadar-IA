from worker.connectors.generic_html import GenericHtmlConnector
from worker.connectors.grants_gov import GrantsGovConnector
from worker.connectors.grants_gov_rss import GrantsGovRssConnector
from worker.connectors.apc_colombia import ApcColombiaConnector
from worker.connectors.api import ApiConnector
from worker.connectors.eu_funding_tenders import EuFundingTendersConnector
from worker.connectors.icetex import IcetexConnector
from worker.connectors.innovamos import InnovamosConnector
from worker.connectors.hybrid import HybridConnector
from worker.connectors.nsf import NSFFundingConnector, NSFFundingRssConnector
from worker.connectors.manual import ManualConnector
from worker.connectors.innpulsa import InnpulsaConnector
from worker.connectors.minciencias import MincienciasConnector
from worker.connectors.mineducacion import MineducacionConnector
from worker.connectors.unesco import UNESCOConnector
from worker.connectors.pdf import PdfConnector
from worker.connectors.rss import RssConnector
from worker.connectors.simpler_grants import SimplerGrantsConnector
from worker.connectors.undef import UNDEFConnector
from worker.connectors.ukri import UKRIConnector
from worker.connectors.unwomen_innovate import UnwomenInnovateConnector
from worker.connectors.wordpress_grants import WordPressGrantsConnector
from worker.connectors.horizon_sedia import HorizonSediaConnector
from worker.connectors.mincit import MincitConvocatoriasConnector
from worker.connectors.wellcome import WellcomeConnector


WORDPRESS_GRANT_SOURCE_KEYS = {
    "novo-nordisk-grants",
}


def _wordpress_connector(source_key: str, base_url: str) -> WordPressGrantsConnector:
    defaults = {
        "novo-nordisk-grants": {
            "entity_name": "Novo Nordisk Foundation",
            "default_country": "Denmark",
            "allowed_domains": ["novonordiskfonden.dk"],
        },
    }
    config = defaults.get(source_key, {})
    return WordPressGrantsConnector(
        source_key,
        base_url,
        entity_name=config.get("entity_name"),
        default_country=config.get("default_country", "Por validar"),
        allowed_domains=config.get("allowed_domains"),
    )


def connector_for(source_key: str, base_url: str | None = None, source_type: str | None = None):
    if source_key == "grants-gov":
        return GrantsGovConnector(base_url)
    if source_key == "minciencias":
        return MincienciasConnector(base_url)
    if source_key in {"icetex-vigentes", "icetex-otras-becas"}:
        return IcetexConnector(base_url)
    if source_key == "mineducacion-becas":
        return MineducacionConnector(base_url)
    if source_key == "innpulsa":
        return InnpulsaConnector(base_url)
    if source_key == "apc-colombia":
        return ApcColombiaConnector(base_url)
    if source_key == "eu-funding-tenders":
        return EuFundingTendersConnector(base_url)
    if source_key == "nsf-funding":
        return NSFFundingConnector(base_url)
    if source_key == "nsf-funding-rss":
        return NSFFundingRssConnector(source_key, base_url or "")
    if source_key in {"innovamos-global-innovation-fund", "innovamos-fid"}:
        return InnovamosConnector(source_key, base_url)
    if source_key == "ukri-opportunities":
        return UKRIConnector(base_url)
    if source_key == "unesco-call-for-proposals":
        return UNESCOConnector(base_url)
    if source_key == "undef":
        return UNDEFConnector(base_url)
    if source_key == "simpler-grants":
        return SimplerGrantsConnector(base_url)
    if source_key in {"grants-gov-rss", "grants-gov-forecast"}:
        return GrantsGovRssConnector(source_key, base_url or "")
    if source_key == "unwomen-innovate":
        return UnwomenInnovateConnector(base_url)
    if source_key == "horizon-europe-sedia":
        return HorizonSediaConnector(base_url)
    if source_key == "wellcome-grants":
        return WellcomeConnector(base_url)
    if source_key == "mincit-innovacion":
        return MincitConvocatoriasConnector(base_url)
    if source_key in WORDPRESS_GRANT_SOURCE_KEYS or "/wp-json/wp/v2/" in (base_url or ""):
        return _wordpress_connector(source_key, base_url or "")
    if source_type == "manual":
        return ManualConnector(source_key, base_url or "")
    if source_type == "pdf":
        return PdfConnector(source_key, base_url or "")
    if source_type == "hybrid":
        return HybridConnector(source_key, base_url or "")
    if source_type == "api":
        return ApiConnector(source_key, base_url or "")
    if source_type == "rss":
        return RssConnector(source_key, base_url or "")
    if source_key.endswith("-rss") or (base_url or "").lower().endswith((".xml", ".rss")):
        return RssConnector(source_key, base_url or "")
    return GenericHtmlConnector(source_key, base_url or "")
