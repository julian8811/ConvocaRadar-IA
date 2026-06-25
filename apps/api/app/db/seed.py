from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal, create_all
from app.models import Organization, OrganizationProfile, Source, User


def seed_default_sources(db, organization: Organization) -> dict[str, int]:
    source_definitions = [
        {
            "key": "simpler-grants",
            "name": "Simpler Grants Search",
            "base_url": "https://simpler.grants.gov/search",
            "country": "United States",
            "region": "North America",
            "source_type": "html",
            "category": ["grants", "federal funding"],
            "allowed_domains": ["simpler.grants.gov"],
        },
        {
            "key": "grants-gov-forecast",
            "name": "Grants.gov Forecast Feed",
            "base_url": "https://www.grants.gov/rss/GG_ForecastOpportunities.xml",
            "country": "United States",
            "region": "North America",
            "source_type": "rss",
            "category": ["grants", "federal funding"],
            "allowed_domains": ["www.grants.gov"],
        },
        {
            "key": "grants-gov",
            "name": "Grants.gov Search API",
            "base_url": "https://api.grants.gov/v1/api/search2",
            "country": "United States",
            "region": "North America",
            "source_type": "api",
            "category": ["grants", "federal funding"],
            "allowed_domains": ["api.grants.gov"],
        },
        {
            "key": "grants-gov-rss",
            "name": "Grants.gov RSS Opportunities",
            "base_url": "https://www.grants.gov/rss/GG_OppModByCategory.xml",
            "country": "United States",
            "region": "North America",
            "source_type": "rss",
            "category": ["grants", "federal funding", "rss"],
            "allowed_domains": ["www.grants.gov"],
        },
        {
            "key": "nsf-funding-rss",
            "name": "NSF Funding Opportunities RSS",
            "base_url": "https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml",
            "country": "United States",
            "region": "North America",
            "source_type": "rss",
            "category": ["grants", "research", "innovation"],
            "allowed_domains": ["nsf.gov"],
        },
        {
            "key": "nsf-funding",
            "name": "NSF Funding Search",
            "base_url": "https://www.nsf.gov/funding",
            "country": "United States",
            "region": "North America",
            "source_type": "html",
            "category": ["grants", "research", "innovation"],
            "allowed_domains": ["nsf.gov"],
        },
        {
            "key": "minciencias",
            "name": "Minciencias Convocatorias",
            "base_url": "https://minciencias.gov.co/convocatorias/todas",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["convocatorias", "ciencia", "innovacion"],
            "allowed_domains": ["minciencias.gov.co"],
        },
        {
            "key": "icetex-vigentes",
            "name": "ICETEX Becas Vigentes",
            "base_url": "https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["becas", "cooperacion", "educacion"],
            "allowed_domains": ["web.icetex.gov.co"],
        },
        {
            "key": "icetex-otras-becas",
            "name": "ICETEX Otras Becas",
            "base_url": "https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["becas", "cooperacion", "educacion"],
            "allowed_domains": ["web.icetex.gov.co"],
        },
        {
            "key": "mineducacion-becas",
            "name": "MEN Becas y Convocatorias",
            "base_url": "https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["becas", "cooperacion", "educacion"],
            "allowed_domains": ["mineducacion.gov.co", "www.mineducacion.gov.co"],
        },
        {
            "key": "innpulsa",
            "name": "iNNpulsa Convocatorias",
            "base_url": "https://convocatorias.innpulsacolombia.com/api/convocatorias?active_only=true&include_private=false&include_archive=false",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "api",
            "category": ["convocatorias", "emprendimiento", "innovacion"],
            "allowed_domains": ["innpulsacolombia.com", "convocatorias.innpulsacolombia.com"],
        },
        {
            "key": "apc-colombia",
            "name": "APC Colombia Convocatorias",
            "base_url": "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["convocatorias", "cooperacion", "internacional"],
            "allowed_domains": ["apccolombia.gov.co"],
        },
        {
            "key": "eu-funding-tenders",
            "name": "EU Funding & Tenders",
            "base_url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals",
            "country": "European Union",
            "region": "Europe",
            "source_type": "hybrid",
            "category": ["grants", "research", "innovation"],
            "allowed_domains": ["ec.europa.eu"],
        },
        {
            "key": "innovamos-global-innovation-fund",
            "name": "Innovamos - Global Innovation Fund",
            "base_url": "https://www.innovamos.gov.co/instrumentos/convocatoria-subvenciones-a-proyectos-en-alianza-con",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["innovacion", "cooperacion", "financiacion"],
            "allowed_domains": ["innovamos.gov.co", "www.innovamos.gov.co"],
        },
        {
            "key": "innovamos-fid",
            "name": "Innovamos - Fondo para la Innovación en el Desarrollo",
            "base_url": "https://www.innovamos.gov.co/instrumentos/internacional-proyectos-fondo-para-la-innovacion-en",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["innovacion", "cooperacion", "financiacion"],
            "allowed_domains": ["innovamos.gov.co", "www.innovamos.gov.co"],
        },
        {
            "key": "ukri-opportunities",
            "name": "UKRI Funding Finder",
            "base_url": "https://www.ukri.org/opportunity/",
            "country": "United Kingdom",
            "region": "Europe",
            "source_type": "html",
            "category": ["grants", "research", "innovation"],
            "allowed_domains": ["ukri.org", "www.ukri.org"],
        },
        {
            "key": "unesco-call-for-proposals",
            "name": "UNESCO Call for Proposals",
            "base_url": "https://www.unesco.org/en/articles/call-proposals",
            "country": "International",
            "region": "Global",
            "source_type": "html",
            "category": ["cooperation", "research", "innovation"],
            "allowed_domains": ["unesco.org", "www.unesco.org"],
        },
        {
            "key": "undef",
            "name": "UN Democracy Fund",
            "base_url": "https://www.un.org/democracyfund/en/apply-for-funding",
            "country": "International",
            "region": "Global",
            "source_type": "html",
            "category": ["cooperation", "governance", "funding"],
            "allowed_domains": ["un.org", "www.un.org"],
        },
        {
            "key": "unwomen-innovate",
            "name": "UN Women Innovation Calls",
            "base_url": "https://www.unwomen.org/en/how-we-work/innovation-and-technology",
            "country": "International",
            "region": "Global",
            "source_type": "html",
            "category": ["innovation", "cooperation", "global"],
            "allowed_domains": ["unwomen.org"],
        },
        {
            "key": "novo-nordisk-grants",
            "name": "Novo Nordisk Foundation Grants",
            "base_url": "https://novonordiskfonden.dk/wp-json/wp/v2/grant?per_page=100&status=publish",
            "country": "Denmark",
            "region": "Europe",
            "source_type": "api",
            "category": ["grants", "health", "biotech", "research"],
            "allowed_domains": ["novonordiskfonden.dk"],
            "scraping_frequency": "daily",
        },
        {
            "key": "wellcome-grants",
            "name": "Wellcome Trust Funding",
            "base_url": "https://wellcome.org/research-funding/schemes",
            "country": "United Kingdom",
            "region": "Europe",
            "source_type": "html",
            "category": ["grants", "health", "research"],
            "allowed_domains": ["wellcome.org", "www.wellcome.org"],
            "scraping_frequency": "weekly",
        },
        {
            "key": "horizon-europe-sedia",
            "name": "Horizon Europe SEDIA API",
            "base_url": "https://api.tech.ec.europa.eu/search-api/prod/rest/search",
            "country": "European Union",
            "region": "Europe",
            "source_type": "api",
            "category": ["grants", "research", "innovation", "horizon europe"],
            "allowed_domains": ["api.tech.ec.europa.eu", "ec.europa.eu"],
            "scraping_frequency": "daily",
        },
        {
            "key": "gates-foundation-grants",
            "name": "Gates Foundation Open Opportunities",
            "base_url": "https://www.gatesfoundation.org/about/how-we-work/grants",
            "country": "International",
            "region": "Global",
            "source_type": "html",
            "category": ["grants", "health", "development"],
            "allowed_domains": ["gatesfoundation.org", "www.gatesfoundation.org"],
            "scraping_frequency": "weekly",
        },
        {
            "key": "dfg-grants",
            "name": "DFG Funding Opportunities",
            "base_url": "https://www.dfg.de/en/research_funding/",
            "country": "Germany",
            "region": "Europe",
            "source_type": "html",
            "category": ["grants", "research", "funding"],
            "allowed_domains": ["dfg.de", "www.dfg.de"],
            "scraping_frequency": "weekly",
        },
        {
            "key": "colfuturo-convocatorias",
            "name": "Colfuturo Convocatorias",
            "base_url": "https://www.colfuturo.org/convocatorias/",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["becas", "cooperacion", "educacion"],
            "allowed_domains": ["colfuturo.org", "www.colfuturo.org"],
            "scraping_frequency": "daily",
        },
        {
            "key": "mincit-innovacion",
            "name": "MinCIT Convocatorias",
            "base_url": "https://www.mincit.gov.co/convocatorias",
            "country": "Colombia",
            "region": "LatAm",
            "source_type": "html",
            "category": ["convocatorias", "innovacion", "emprendimiento"],
            "allowed_domains": ["mincit.gov.co", "www.mincit.gov.co"],
            "scraping_frequency": "daily",
        },
    ]

    inserted = 0
    updated = 0
    for definition in source_definitions:
        source = db.scalar(select(Source).where(Source.key == definition["key"]))
        if source:
            source.organization_id = organization.id
            source.name = definition["name"]
            source.base_url = definition["base_url"]
            source.country = definition["country"]
            source.region = definition["region"]
            source.source_type = definition["source_type"]
            source.category = definition["category"]
            source.scraping_frequency = definition.get("scraping_frequency", "daily")
            source.allowed_domains = definition["allowed_domains"]
            source.enabled = True
            updated += 1
            continue
        db.add(
            Source(
                organization_id=organization.id,
                name=definition["name"],
                key=definition["key"],
                base_url=definition["base_url"],
                country=definition["country"],
                region=definition["region"],
                source_type=definition["source_type"],
                category=definition["category"],
                scraping_frequency=definition.get("scraping_frequency", "daily"),
                allowed_domains=definition["allowed_domains"],
            )
        )
        inserted += 1
    return {"inserted": inserted, "updated": updated, "total": len(source_definitions)}


def seed() -> None:
    create_all()
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        if not organization:
            organization = Organization(
                name="ConvocaRadar Local",
                slug="convocaradar-local",
                type="university",
                country="Colombia",
                website="https://convocaradar.local",
            )
            db.add(organization)
            db.flush()
            db.add(
                OrganizationProfile(
                    organization_id=organization.id,
                    description="Perfil local para vigilancia de innovacion, investigacion y emprendimiento.",
                    country="Colombia",
                    regions_of_interest=["LatAm", "Global"],
                    organization_type="university",
                    areas_of_interest=["innovacion", "investigacion", "inteligencia artificial", "sostenibilidad"],
                    funding_types=["grant", "cofinancing", "award"],
                    min_funding_amount=10000000,
                    max_funding_amount=500000000,
                    preferred_currencies=["COP", "USD", "EUR"],
                    eligible_international=True,
                    languages=["es", "en"],
                    has_research_groups=True,
                    has_company_partners=True,
                    has_university_partners=True,
                    application_capacity="high",
                )
            )

        user = db.scalar(select(User).where(User.email == "admin@convocaradar.io"))
        if not user:
            db.add(
                User(
                    email="admin@convocaradar.io",
                    name="Admin ConvocaRadar",
                    password_hash=hash_password("ConvocaRadarLocal123!"),
                    role="admin",
                    organization_id=organization.id,
                )
            )

        seed_default_sources(db, organization)

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()

