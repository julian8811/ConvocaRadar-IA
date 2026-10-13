"""041 pilot gate (X3 Parte 1): vigencia, pertinencia y duplicados ENTRE las cinco.

Cero network: fixtures en memoria + AST sobre seed.py. No toca DB.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import urlparse

BATCH_KEYS = (
    "fontagro-convocatorias",
    "fundacion-biodiversidad-convocatorias",
    "eu-life-calls-cinea",
    "biodiversa-calls",
    "fondo-accion-convocatorias",
)

# Fixtures: 2 candidatos por fuente (título, url, deadline o unknown).
FIXTURES: dict[str, list[dict]] = {
    "fontagro-convocatorias": [
        {"title": "Convocatoria 2027 FONTAGRO I+D+i agroalimentaria", "url": "https://fontagro.org/es/iniciativas/convocatorias/convocatoria-2027", "deadline": "2027-03-31", "status": "open"},
        {"title": "Convocatoria 2026 consorcios regionales de innovacion", "url": "https://fontagro.org/es/iniciativas/convocatorias/convocatoria-2026", "deadline": None, "status": "unknown"},
    ],
    "fundacion-biodiversidad-convocatorias": [
        {"title": "Convocatoria para proyectos de Educacion Ambiental 2026", "url": "https://fundacion-biodiversidad.es/otras_convocatorias/convocatoria-para-proyectos-de-educacion-ambiental-2", "deadline": "2026-09-30", "status": "open"},
        {"title": "Convocatoria renaturalizacion y resiliencia de ciudades 2026", "url": "https://fundacion-biodiversidad.es/otras_convocatorias/convocatoria-infraestructura-verde-ciudades-2026", "deadline": None, "status": "unknown"},
    ],
    "eu-life-calls-cinea": [
        {"title": "LIFE 2026 Standard Action Projects Circular Economy call", "url": "https://cinea.ec.europa.eu/life-calls-proposals-2026/sap-circular-economy", "deadline": "2026-09-23", "status": "open"},
        {"title": "LIFE 2026 Nature and Biodiversity call for proposals", "url": "https://cinea.ec.europa.eu/life-calls-proposals-2026/sap-nature-biodiversity", "deadline": None, "status": "unknown"},
    ],
    "biodiversa-calls": [
        {"title": "BiodivFuture 2026-2027 Joint Call for transnational research", "url": "https://www.biodiversa.eu/2026/06/09/2026-2027-joint-call", "deadline": "2026-11-10", "status": "open"},
        {"title": "Biodiversa+ flagship programme transnational call 2026", "url": "https://www.biodiversa.eu/research-funding/flagship-2026", "deadline": None, "status": "unknown"},
    ],
    "fondo-accion-convocatorias": [
        {"title": "Becas Laboratorio Acciones Escolares Climaticas CSIELO", "url": "https://fondoaccion.org/2026/08/12/lab-csielo-convocatoria/", "deadline": "2026-10-15", "status": "open"},
        {"title": "Convocatoria Territorios Mas Sostenibles adaptacion climatica", "url": "https://fondoaccion.org/convocatorias/territorios-mas-sostenibles", "deadline": None, "status": "unknown"},
    ],
}

NOISE_KEYWORDS = (
    "empleo", "empleos", "job", "jobs", "hiring", "vacante", "vacantes",
    "noticia", "noticias", "news", "press release", "blog post",
    "oferta laboral", "bolsa de trabajo",
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _seed_definitions_by_key() -> dict[str, dict]:
    seed_path = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "seed_default_sources":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "source_definitions":
                    return {item["key"]: item for item in ast.literal_eval(stmt.value)}
    raise AssertionError("source_definitions not found")


def test_041_pilot_vigencia():
    """Cada candidato: fecha de cierre presente (YYYY-MM-DD) o marcado unknown."""
    for key, candidates in FIXTURES.items():
        assert candidates, f"{key} sin fixtures"
        for cand in candidates:
            if cand["status"] == "unknown":
                assert cand["deadline"] is None, f"{key} unknown debe tener deadline None"
            else:
                assert cand["deadline"] is not None, f"{key} {cand['title']!r} sin fecha ni marca unknown"
                assert DATE_RE.match(cand["deadline"]), f"{key} fecha inválida: {cand['deadline']!r}"


def test_041_pilot_pertinencia():
    """Ningún candidato parece empleo o noticia (keywords en título+url)."""
    for key, candidates in FIXTURES.items():
        for cand in candidates:
            blob = f"{cand['title']} {cand['url']}".lower()
            hits = [kw for kw in NOISE_KEYWORDS if kw in blob]
            assert hits == [], f"{key} {cand['title']!r} parece ruido: {hits}"


def test_041_pilot_no_duplicates_between_five():
    """Duplicados ENTRE las cinco: claves, dominios, URLs y programas distintos."""
    defs = _seed_definitions_by_key()
    batch = {k: defs[k] for k in BATCH_KEYS}

    # Claves únicas (trivially) y presentes.
    assert len(set(BATCH_KEYS)) == 5

    # Dominios allowlist disjuntos entre las cinco.
    seen_domains: dict[str, str] = {}
    for key, definition in batch.items():
        for domain in definition["allowed_domains"]:
            assert domain not in seen_domains, (
                f"dominio {domain!r} compartido entre {seen_domains[domain]} y {key}"
            )
            seen_domains[domain] = key

    # Hosts de base_url disjuntos.
    seen_hosts: dict[str, str] = {}
    for key, definition in batch.items():
        host = urlparse(definition["base_url"]).netloc.lower()
        assert host not in seen_hosts, (
            f"host {host!r} compartido entre {seen_hosts[host]} y {key}"
        )
        seen_hosts[host] = key

    # base_url exactas distintas.
    urls = [definition["base_url"] for definition in batch.values()]
    assert len(set(urls)) == 5, f"base_url duplicadas: {urls}"

    # URLs de fixtures: sin solapamiento entre fuentes (path normalizado).
    seen_paths: dict[str, str] = {}
    for key, candidates in FIXTURES.items():
        for cand in candidates:
            parsed = urlparse(cand["url"])
            norm = (parsed.netloc.lower(), parsed.path.rstrip("/").lower())
            assert norm not in seen_paths, (
                f"URL duplicada entre {seen_paths[norm]} y {key}: {cand['url']}"
            )
            seen_paths[norm] = key

    # Programas: ningún título de fixture aparece en otra fuente (tokens distintivos).
    for key_a, cands_a in FIXTURES.items():
        for key_b, cands_b in FIXTURES.items():
            if key_a >= key_b:
                continue
            titles_a = {c["title"].lower() for c in cands_a}
            titles_b = {c["title"].lower() for c in cands_b}
            assert titles_a.isdisjoint(titles_b), (
                f"títulos solapados entre {key_a} y {key_b}: {titles_a & titles_b}"
            )
