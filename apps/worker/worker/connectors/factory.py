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
from worker.connectors.bdn_convocatorias import BdnConvocatoriasConnector
from worker.connectors.heading_list_html import HeadingListHtmlConnector
from worker.connectors.idrc_funding import IdrcFundingConnector
from worker.connectors.usaid_grants import UsaidGrantsConnector
from worker.connectors.giz_funding import GizFundingConnector
from worker.connectors.cordis_h2020 import CordisH2020Connector
from worker.connectors.eic_accelerator import EicAcceleratorConnector
from worker.connectors.global_innovation_fund import GlobalInnovationFundConnector
from worker.connectors.procolombia_convocatorias import ProcolombiaConvocatoriasConnector
from worker.connectors.anii_uruguay import AniiUruguayConnector


WORDPRESS_GRANT_SOURCE_KEYS = {
    "novo-nordisk-grants",
}

BDN_CONVOCATORIAS_SOURCE_KEYS = {
    "cdti-convocatorias": {
        "search_query": "CDTI",
        "entity_name": "CDTI",
        "default_country": "Spain",
        "allowed_domains": ["infosubvenciones.es", "www.infosubvenciones.es", "cdti.es", "www.cdti.es"],
    },
    "isciii-convocatorias": {
        "search_query": "Instituto de Salud Carlos III",
        "entity_name": "ISCIII",
        "default_country": "Spain",
        "allowed_domains": ["infosubvenciones.es", "www.infosubvenciones.es", "isciii.es", "www.isciii.es"],
    },
}

HEADING_LIST_SOURCE_KEYS = {
    "lundbeck-foundation": {
        "entity_name": "Lundbeck Foundation",
        "default_country": "Denmark",
        "allowed_domains": ["lundbeckfonden.com"],
    },
    "velux-foundation": {
        "entity_name": "Velux Fonden",
        "default_country": "Denmark",
        "allowed_domains": ["veluxfonden.dk"],
    },
}


def _bdn_connector(source_key: str, base_url: str) -> BdnConvocatoriasConnector:
    config = BDN_CONVOCATORIAS_SOURCE_KEYS[source_key]
    return BdnConvocatoriasConnector(
        source_key,
        base_url,
        search_query=config["search_query"],
        entity_name=config["entity_name"],
        default_country=config.get("default_country", "Spain"),
        allowed_domains=config.get("allowed_domains"),
    )


def _heading_list_connector(source_key: str, base_url: str) -> HeadingListHtmlConnector:
    config = HEADING_LIST_SOURCE_KEYS[source_key]
    return HeadingListHtmlConnector(
        source_key,
        base_url,
        entity_name=config["entity_name"],
        default_country=config["default_country"],
        allowed_domains=config["allowed_domains"],
    )


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
    if source_key == "lundbeck-foundation":
        return _heading_list_connector(source_key, base_url or "")
    if source_key == "velux-foundation":
        return _heading_list_connector(source_key, base_url or "")
    if source_key in BDN_CONVOCATORIAS_SOURCE_KEYS:
        return _bdn_connector(source_key, base_url or "")
    if source_key == "idrc-funding":
        return IdrcFundingConnector(base_url)
    if source_key == "usaid-grants":
        return UsaidGrantsConnector(base_url)
    if source_key == "giz-funding":
        return GizFundingConnector(base_url)
    if source_key == "cordis-h2020":
        return CordisH2020Connector(base_url)
    if source_key == "eic-accelerator":
        return EicAcceleratorConnector(base_url)
    if source_key == "global-innovation-fund":
        return GlobalInnovationFundConnector(base_url)
    if source_key == "procolombia-convocatorias":
        return ProcolombiaConvocatoriasConnector(base_url)
    if source_key == "anii-uruguay":
        return AniiUruguayConnector(base_url)
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
