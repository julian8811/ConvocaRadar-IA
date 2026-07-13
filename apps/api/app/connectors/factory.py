from app.connectors.configurable_html import ConfigurableHtmlConnector
from app.connectors.registry import get_connector
from app.connectors.generic_html import GenericHtmlConnector
from app.connectors.grants_gov import GrantsGovConnector
from app.connectors.grants_gov_rss import GrantsGovRssConnector
from app.connectors.apc_colombia import ApcColombiaConnector
from app.connectors.api import ApiConnector
from app.connectors.eu_funding_tenders import EuFundingTendersConnector
from app.connectors.icetex import IcetexConnector
from app.connectors.innovamos import InnovamosConnector
from app.connectors.hybrid import HybridConnector
from app.connectors.nsf import NSFFundingConnector, NSFFundingRssConnector
from app.connectors.manual import ManualConnector
from app.connectors.innpulsa import InnpulsaConnector
from app.connectors.minciencias import MincienciasConnector
from app.connectors.mineducacion import MineducacionConnector
from app.connectors.unesco import UNESCOConnector
from app.connectors.pdf import PdfConnector
from app.connectors.rss import RssConnector
from app.connectors.simpler_grants import SimplerGrantsConnector
from app.connectors.undef import UNDEFConnector
from app.connectors.ukri import UKRIConnector
from app.connectors.unwomen_innovate import UnwomenInnovateConnector
from app.connectors.wordpress_grants import WordPressGrantsConnector
from app.connectors.horizon_sedia import HorizonSediaConnector
from app.connectors.mincit import MincitConvocatoriasConnector
from app.connectors.wellcome import WellcomeConnector
from app.connectors.bdn_convocatorias import BdnConvocatoriasConnector
from app.connectors.heading_list_html import HeadingListHtmlConnector
from app.connectors.idrc_funding import IdrcFundingConnector
from app.connectors.usaid_grants import UsaidGrantsConnector
from app.connectors.giz_funding import GizFundingConnector
# from app.connectors.cordis_h2020 import CordisH2020Connector  # Removed: Horizon 2020 ended in 2020
from app.connectors.eic_accelerator import EicAcceleratorConnector
from app.connectors.global_innovation_fund import GlobalInnovationFundConnector
from app.connectors.procolombia_convocatorias import ProcolombiaConvocatoriasConnector
from app.connectors.anii_uruguay import AniiUruguayConnector


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


def connector_for(source_key: str, base_url: str | None = None, source_type: str | None = None, *, entity_name: str | None = None, default_country: str | None = None, default_categories: list[str] | None = None, connector_config: dict | None = None):
    # ── Special construction cases (non-standard __init__) ────────────────
    # These connectors take ``source_key`` as a positional argument, so
    # the standard ``cls(base_url, **kwargs)`` registry pattern doesn't
    # fit.  They *are* registered for introspection but must be constructed
    # explicitly here during the gradual migration.
    if source_key in {"grants-gov-rss", "grants-gov-forecast"}:
        return GrantsGovRssConnector(source_key, base_url or "")

    # ── Connector registry (gradual migration) ───────────────────────────
    # Registered connectors with standard ``__init__(self, base_url)`` are
    # handled here.  Unregistered keys raise ``KeyError`` and fall through
    # to the traditional if-elif chain below.
    try:
        return get_connector(source_key, base_url)
    except KeyError:
        pass

    # ── Traditional if-elif chain (connectors that use non-standard
    #    __init__ or special construction. Standard connectors are
    #    resolved via @register() in the registry above). ──────────────
    if source_key in {"lundbeck-foundation", "velux-foundation"}:
        return _heading_list_connector(source_key, base_url or "")
    if source_key in BDN_CONVOCATORIAS_SOURCE_KEYS:
        return _bdn_connector(source_key, base_url or "")
    if source_key == "giz-funding":
        return GizFundingConnector(base_url)
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
    # SDD Change A: if a declarative connector_config is provided, use
    # ConfigurableHtmlConnector instead of hardcoded GenericHtmlConnector.
    if connector_config is not None:
        return ConfigurableHtmlConnector(
            source_key, base_url or "",
            connector_config,
            entity_name=entity_name,
            default_country=default_country,
            default_categories=default_categories,
        )
    return GenericHtmlConnector(
        source_key, base_url or "",
        entity_name=entity_name,
        default_country=default_country,
        default_categories=default_categories,
    )
