"""Remapeo canónico de 10 fuentes muertas (P0, S3/S4/S6).

Revision ID: 0019_canonical_source_urls
Revises: 0018_unique_opportunity_score

Lleva los ``base_url`` + ``allowed_domains`` canónicos — pineados en
``CANONICAL_SEEDS`` de tests/test_seed_canonical_urls.py y ya presentes
en ``app/db/seed.py`` (el seed solo rige instalaciones nuevas) — a las
filas existentes de ``sources``.

Cada UPDATE es idempotente por clave: re-correr el upgrade sobre una
fila ya-canónica la deja igual. El downgrade revierte a las URLs viejas
(404 probadas en reports/live-probe-*/live-probe-real.json).

No toca: sgc-convocatorias, universidad-nacional-colombia,
flacso-convocatorias, rutann-convocatorias, camara-comercio-cali,
camara-comercio-medellin (ni ninguna otra clave).
"""

import json

from alembic import op
from sqlalchemy import text

revision = "0019_canonical_source_urls"
down_revision = "0018_unique_opportunity_score"
branch_labels = None
depends_on = None

# key -> (canonical base_url, canonical allowed_domains).
# Fuente de verdad: CANONICAL_SEEDS en tests/test_seed_canonical_urls.py.
CANONICAL = {
    "oei-convocatorias": (
        "https://oei.int/licitaciones-y-convocatorias/",
        ["oei.int", "www.oei.int"],
    ),
    "cepal-convocatorias": (
        "https://www.cepal.org/es",
        ["cepal.org", "www.cepal.org"],
    ),
    "finagro-lec-2026": (
        "https://www.finagro.com.co/",
        ["finagro.com.co", "www.finagro.com.co"],
    ),
    "green-climate-fund": (
        "https://www.greenclimate.fund/access-funding",
        ["greenclimate.fund", "www.greenclimate.fund"],
    ),
    "supersolidaria-convocatorias": (
        "https://www.supersolidaria.gov.co/es/content/convocatorias-superintendencias",
        ["supersolidaria.gov.co", "www.supersolidaria.gov.co"],
    ),
    "global-environment-facility": (
        "https://www.thegef.org/who-we-are/funding",
        ["thegef.org", "www.thegef.org"],
    ),
    "giz-alemania": (
        "https://www.giz.de/en/partner/funding",
        ["giz.de", "www.giz.de", "ausschreibungen.giz.de"],
    ),
    "anp-brasil": (
        "https://www.gov.br/anp/pt-br/assuntos/tecnologia-meio-ambiente/pesquisa-desenvolvimento-inovacao",
        ["gov.br", "anp.gov.br"],
    ),
    "procolombia-inversion": (
        "https://investincolombia.com.co/es/buscador-oportunidades-inversion",
        ["investincolombia.com.co"],
    ),
    "inct-brasil": (
        "https://www.gov.br/cnpq/pt-br/chamadas/abertas-para-submissao",
        ["gov.br", "www.gov.br"],
    ),
}

# key -> (old base_url, old allowed_domains) previos al re-mapeo.
# Las URLs viejas son las 404 de reports/live-probe-*/live-probe-real.json.
PREVIOUS = {
    "oei-convocatorias": (
        "https://oei.int/oficinas/secretaria-general/convocatorias",
        ["oei.int", "www.oei.int"],
    ),
    "cepal-convocatorias": (
        "https://www.cepal.org/es/convocatorias",
        ["cepal.org", "www.cepal.org"],
    ),
    "finagro-lec-2026": (
        "https://www.finagro.com.co/lineas-especiales-credito-lec-finagro-2026",
        ["finagro.com.co", "www.finagro.com.co"],
    ),
    "green-climate-fund": (
        "https://www.greenclimate.fund/projects/call-for-proposals",
        ["greenclimate.fund", "www.greenclimate.fund"],
    ),
    "supersolidaria-convocatorias": (
        "https://www.supersolidaria.gov.co/es/convocatorias",
        ["supersolidaria.gov.co", "www.supersolidaria.gov.co"],
    ),
    "global-environment-facility": (
        "https://www.thegef.org/projects-operations/calls-for-proposals",
        ["thegef.org", "www.thegef.org"],
    ),
    "giz-alemania": (
        "https://www.giz.de/en/html/ausschreibungen.html",
        ["giz.de", "www.giz.de"],
    ),
    "anp-brasil": (
        "https://www.gov.br/anp/pt-br/assuntos/pesquisa-desenvolvimento-e-inovacao",
        ["gov.br", "anp.gov.br"],
    ),
    "procolombia-inversion": (
        "https://investincolombia.com.co/es/convocatorias",
        ["investincolombia.com.co"],
    ),
    "inct-brasil": (
        "https://www.gov.br/cnpq/pt-br/assuntos/institutos-nacionais-de-ciencia-e-tecnologia",
        ["gov.br"],
    ),
}


def _apply(mapping: dict[str, tuple[str, list[str]]]) -> None:
    # text() con JSON serializado — mismo precedente que 0012: en Postgres
    # el bindparam queda sin tipo y el servidor lo coerciona a la columna
    # JSON; con table()/String SQLAlchemy lo tipaba VARCHAR y Postgres
    # rechazaba (DatatypeMismatch, tumbó el api en el primer intento). En
    # SQLite el texto JSON se guarda igual y el test lo lee como lista.
    bind = op.get_bind()
    for key, (base_url, allowed_domains) in mapping.items():
        bind.execute(
            text(
                "UPDATE sources SET base_url = :base_url, "
                "allowed_domains = :allowed_domains, "
                "updated_at = CURRENT_TIMESTAMP WHERE key = :key"
            ),
            {
                "key": key,
                "base_url": base_url,
                "allowed_domains": json.dumps(allowed_domains),
            },
        )


def upgrade() -> None:
    _apply(CANONICAL)


def downgrade() -> None:
    _apply(PREVIOUS)
