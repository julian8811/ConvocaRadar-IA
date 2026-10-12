"""T2 rules-based sector classifier (deterministic keyword layer).

Taxonomy ``SECTOR_TAXONOMY_V1`` is the closed 11-sector list from T1.
``classify_by_rules`` is a pure function: no I/O, no network.

Confidence model (documented, explicit):
  score(sector) = sum of weights of the distinct keywords of that
  sector found in the normalized ``title + description`` text.
  confidence = min(1.0, winning_score / _STRONG_MATCH), where
  ``_STRONG_MATCH = 6.0`` (roughly two strong weight-3 hits).
  No keyword hit in any sector -> ("otros", 0.0).

Matching details: accent/case-insensitive, whole-word with optional
plural suffix (so "cultura" never fires inside "acuicultura", and
"state-of-the-art" never fires "art" as a standalone word match...
hyphenated compounds still count as word boundaries, which is accepted
noise). Ties resolve deterministically in dict insertion order, with
educación/salud/investigación ranked before innovación so that
education/health/research signals win exact ties.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import unicodedata

SECTOR_TAXONOMY_V1: tuple[str, ...] = (
    "turismo",
    "investigación",
    "emprendimiento",
    "innovación",
    "transferencia tecnológica",
    "educación",
    "salud",
    "ambiente",
    "cultura",
    "infraestructura",
    "otros",
)

# Normalizer for the strong-match confidence denominator.
_STRONG_MATCH = 6.0

# Sector -> ((keyword, weight), ...). Keywords are matched on
# accent/case-folded text. Insertion order doubles as the tie-break
# priority (first wins exact ties).
_SECTOR_KEYWORDS: dict[str, tuple[tuple[str, float], ...]] = {
    "educación": (
        ("educacion", 3.0),
        ("education", 3.0),
        ("educacao", 3.0),
        ("educativa", 2.0),
        ("educativo", 2.0),
        ("educational", 2.0),
        ("erasmus", 3.0),
        ("diploma", 2.0),
        ("e-learning", 2.0),
        ("elearning", 2.0),
        ("beca", 2.0),
        ("scholarship", 2.0),
        ("pedagogia", 2.0),
        ("pedagogy", 2.0),
        ("ensino", 2.0),
        ("ensenanza", 2.0),
        ("popularizacion de la ciencia", 3.0),
        ("popularizacao da ciencia", 3.0),
        ("divulgacion cientifica", 3.0),
        ("divulgacao cientifica", 3.0),
        ("colegio", 1.0),
        ("escuela", 1.0),
        ("school", 1.0),
        ("escola", 1.0),
        ("curso", 2.0),
        ("courses", 2.0),
        ("teacher", 2.0),
        ("profesor", 1.0),
        ("professor", 1.0),
        ("estudiante", 1.0),
        ("estudante", 1.0),
        ("student", 1.0),
        ("escolar", 1.0),
        ("bildung", 2.0),
        ("formacion", 1.0),
        ("formacao", 1.0),
        ("training", 1.0),
    ),
    "salud": (
        ("salud", 3.0),
        ("saude", 3.0),
        ("hospital", 3.0),
        ("hospitais", 3.0),
        ("nursing", 3.0),
        ("enfermeria", 3.0),
        ("enfermagem", 3.0),
        ("encephalitis", 3.0),
        ("encefalitis", 3.0),
        ("encefalite", 3.0),
        ("health", 2.0),
        ("medical", 2.0),
        ("medico", 2.0),
        ("medicina", 2.0),
        ("medicine", 2.0),
        ("paciente", 2.0),
        ("patient", 2.0),
        ("vacuna", 2.0),
        ("vacina", 2.0),
        ("vaccine", 2.0),
        ("outbreak", 2.0),
        ("brote", 2.0),
        ("surto", 2.0),
        ("epidemiology", 2.0),
        ("epidemiologia", 2.0),
        ("atencion primaria", 2.0),
        ("atencao primaria", 2.0),
        ("primary care", 2.0),
        ("primary health", 2.0),
        ("obesidad", 2.0),
        ("obesidade", 2.0),
        ("obesity", 2.0),
        ("aps universal", 2.0),
        ("aps", 2.0),
        ("alimento", 2.0),
        ("food", 2.0),
        ("enfermedad", 1.0),
        ("disease", 1.0),
        ("doenca", 1.0),
        ("violencia", 1.0),
        ("violence", 1.0),
        ("abuse", 1.0),
        ("abused", 1.0),
        ("abuso", 1.0),
        ("abusado", 1.0),
        ("domestic", 1.0),
        ("nino", 1.0),
        ("crianca", 1.0),
        ("mujer", 1.0),
        ("mulher", 1.0),
        ("women", 1.0),
        ("bienestar", 1.0),
        ("discapacidad", 2.0),
        ("deficiencia", 1.0),
        ("disability", 2.0),
        ("disabilities", 2.0),
        ("bem-estar", 1.0),
        ("wellbeing", 1.0),
        ("well-being", 1.0),
        ("envejecimiento", 1.0),
        ("envelhecimento", 1.0),
        ("ageing", 1.0),
        ("aging", 1.0),
    ),
    "investigación": (
        ("investigador", 3.0),
        ("investigadora", 3.0),
        ("researcher", 3.0),
        ("pesquisador", 3.0),
        ("doctorado", 3.0),
        ("doutorado", 3.0),
        ("doctoral", 3.0),
        ("postdoc", 3.0),
        ("posdoc", 3.0),
        ("postdoctoral", 3.0),
        ("posdoctorado", 3.0),
        ("post-doctoral", 3.0),
        ("pos-doutorado", 3.0),
        ("investigacion", 2.0),
        ("research", 2.0),
        ("pesquisa", 2.0),
        ("ciencia", 2.0),
        ("science", 2.0),
        ("scientific", 2.0),
        ("cientifico", 2.0),
        ("cientifica", 2.0),
        ("cientista", 2.0),
        ("scientist", 2.0),
        ("thesis", 2.0),
        ("tesis", 2.0),
        ("tese", 2.0),
        ("dissertation", 2.0),
        ("dissertacao", 2.0),
        ("bolsa", 2.0),
        ("laboratorio", 2.0),
        ("laboratory", 2.0),
        ("sabbatical", 2.0),
        ("sabatico", 2.0),
        ("phd", 2.0),
    ),
    "innovación": (
        ("innovacion", 3.0),
        ("innovation", 3.0),
        ("inovacao", 3.0),
        ("modernizacion", 2.0),
        ("modernization", 2.0),
        ("modernizacao", 2.0),
        ("industria del futuro", 2.0),
        ("industry of the future", 2.0),
        ("industria do futuro", 2.0),
        ("reindustrializacion", 2.0),
        ("reindustrialization", 2.0),
        ("reindustrializacao", 2.0),
        ("autonomia tecnologica", 2.0),
        ("technological autonomy", 2.0),
        ("tecnologia", 1.0),
        ("technology", 1.0),
        ("technologies", 1.0),
        ("innovative", 1.0),
        ("innovador", 1.0),
        ("innovadora", 1.0),
        ("inovador", 1.0),
    ),
    "transferencia tecnológica": (
        ("transferencia", 3.0),
        ("technology transfer", 3.0),
        ("transferencia de tecnologia", 3.0),
        ("transferencia tecnologica", 3.0),
        ("apropiacion tecnologica", 3.0),
        ("apropriacao tecnologica", 3.0),
        ("patentamiento", 3.0),
        ("patenteamento", 3.0),
        ("patent", 2.0),
        ("patente", 2.0),
        ("extension tecnologica", 2.0),
        ("extensao tecnologica", 2.0),
        ("extensionismo", 2.0),
    ),
    "emprendimiento": (
        ("emprendedor", 3.0),
        ("emprendedora", 3.0),
        ("entrepreneur", 3.0),
        ("empreendedor", 3.0),
        ("emprendimiento", 3.0),
        ("entrepreneurship", 3.0),
        ("empreendedorismo", 3.0),
        ("empreendimento", 3.0),
        ("fondo emprender", 3.0),
        ("mipyme", 3.0),
        ("incubadora", 3.0),
        ("incubator", 3.0),
        ("startup", 2.0),
        ("unidades productivas", 2.0),
        ("unidade produtiva", 2.0),
        ("iniciativas productivas", 2.0),
        ("plan de negocio", 2.0),
        ("business plan", 2.0),
        ("modelo de negocio", 2.0),
        ("business model", 2.0),
        ("desarrollo economico", 2.0),
        ("economic development", 2.0),
        ("desenvolvimento economico", 2.0),
        ("fortalecimiento productivo", 2.0),
        ("fortalecimento produtivo", 2.0),
        ("economia popular", 2.0),
        ("economia campesina", 2.0),
        ("cooperativa popular", 2.0),
        ("capital semilla", 2.0),
        ("seed capital", 2.0),
        ("negocio", 2.0),
        ("emprender", 2.0),
        ("business", 1.0),
    ),
    "turismo": (
        ("turismo", 3.0),
        ("tourism", 3.0),
        ("ecoturismo", 3.0),
        ("ecotourism", 3.0),
        ("blue economy", 3.0),
        ("economia azul", 3.0),
        ("turista", 3.0),
        ("tourist", 3.0),
        ("turistico", 2.0),
        ("turistica", 2.0),
        ("touristic", 2.0),
        ("travel", 2.0),
        ("viaje", 2.0),
        ("viagem", 2.0),
        ("hotel", 2.0),
        ("hotelaria", 2.0),
        ("hoteleria", 2.0),
        ("hospitality", 2.0),
        ("hospitalidade", 2.0),
        ("museum", 2.0),
        ("museo", 2.0),
        ("museu", 2.0),
        ("escultura", 2.0),
        ("sculpture", 2.0),
        ("visitante", 2.0),
        ("visitor", 2.0),
    ),
    "ambiente": (
        ("green climate", 3.0),
        ("medio ambiente", 2.0),
        ("meio ambiente", 2.0),
        ("climate", 2.0),
        ("clima", 2.0),
        ("climatico", 2.0),
        ("environment", 2.0),
        ("environmental", 2.0),
        ("ambiental", 2.0),
        ("sustainability", 2.0),
        ("sustentabilidad", 2.0),
        ("sustentabilidade", 2.0),
        ("sostenible", 2.0),
        ("sustentavel", 2.0),
        ("biodiversidad", 2.0),
        ("biodiversity", 2.0),
        ("biodiversidade", 2.0),
        ("carbono", 2.0),
        ("carbon", 2.0),
        ("bosque", 2.0),
        ("habitat", 2.0),
        ("forest", 2.0),
        ("floresta", 2.0),
        ("cambio climatico", 2.0),
        ("climate change", 2.0),
        ("transicion energetica", 1.0),
        ("transicao energetica", 1.0),
        ("energy transition", 1.0),
    ),
    "cultura": (
        ("cultura", 3.0),
        ("musica", 3.0),
        ("music", 3.0),
        ("culture", 2.0),
        ("cultural", 2.0),
        ("arte", 2.0),
        ("art", 2.0),
        ("danza", 2.0),
        ("dance", 2.0),
        ("danca", 2.0),
        ("teatro", 2.0),
        ("theater", 2.0),
        ("theatre", 2.0),
        ("patrimonio", 2.0),
        ("heritage", 2.0),
        ("festival", 2.0),
        ("cine", 2.0),
        ("cinema", 2.0),
        ("literatura", 2.0),
        ("literature", 2.0),
        ("pintura", 2.0),
        ("painting", 2.0),
        ("creatividad", 2.0),
        ("creativity", 2.0),
        ("criatividade", 2.0),
    ),
    "infraestructura": (
        ("infraestructura", 3.0),
        ("infrastructure", 3.0),
        ("infraestrutura", 3.0),
        ("constructor", 2.0),
        ("constructora", 2.0),
        ("construtora", 2.0),
        ("construccion", 3.0),
        ("construction", 3.0),
        ("construcao", 3.0),
        ("concesion", 2.0),
        ("concessao", 2.0),
        ("concession", 2.0),
        ("obra", 2.0),
        ("instalacion", 2.0),
        ("installation", 2.0),
        ("instalacao", 2.0),
        ("structural", 2.0),
        ("estructural", 2.0),
        ("estrutural", 2.0),
        ("irrigation", 2.0),
        ("riego", 2.0),
        ("irrigacao", 2.0),
        ("dam", 2.0),
        ("represa", 2.0),
        ("pump", 2.0),
        ("bomba", 2.0),
        ("retrofitting", 2.0),
        ("renovacion", 2.0),
        ("renovation", 2.0),
        ("renovacao", 2.0),
        ("seismic", 2.0),
        ("sismico", 2.0),
        ("saneamiento", 2.0),
        ("sanitation", 2.0),
        ("saneamento", 2.0),
        ("servidor", 2.0),
        ("server", 2.0),
        ("puente", 2.0),
        ("bridge", 2.0),
        ("ponte", 2.0),
        ("carretera", 2.0),
        ("road", 2.0),
        ("estrada", 2.0),
        ("procurement of works", 2.0),
        ("exploracion", 1.0),
        ("exploracao", 1.0),
        ("exploration", 1.0),
        ("energia", 1.0),
        ("energie", 1.0),
        ("energetique", 1.0),
        ("energy", 1.0),
        ("energetica", 1.0),
        ("energetico", 1.0),
        ("combustible", 1.0),
        ("combustivel", 1.0),
        ("fuel", 1.0),
        ("gas", 1.0),
        ("resilience", 1.0),
        ("resiliencia", 1.0),
        ("repair", 1.0),
    ),
}

# Precompile whole-word patterns (optional plural suffix) on folded keywords.
_PATTERNS: dict[str, list[tuple[re.Pattern[str], float]]] = {}
for _sector, _pairs in _SECTOR_KEYWORDS.items():
    _compiled: list[tuple[re.Pattern[str], float]] = []
    for _keyword, _weight in _pairs:
        _folded = unicodedata.normalize("NFKD", _keyword.lower())
        _folded = "".join(c for c in _folded if not unicodedata.combining(c))
        _compiled.append(
            (re.compile(r"\b" + re.escape(_folded) + r"(?:s|es)?\b"), _weight)
        )
    _PATTERNS[_sector] = _compiled


def _fold(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


# ── T3 embedding fallback layer ──────────────────────────────────────
# One textual prototype per sector (2-3 sentences ES with key EN/PT
# synonyms). ``classify_by_embedding`` embeds the input text and each
# prototype with the injectable ``embed_fn`` and returns the closest
# sector by cosine similarity when it clears
# ``EMBEDDING_SIMILARITY_THRESHOLD``; otherwise ("otros", 0.0).
# Pure except for ``embed_fn``; zero network in tests (stub).
# Production wiring: ``from app.core.ai import build_embedding_sync``
# and pass it as ``embed_fn`` — needs server infra, verify server-side.

SECTOR_PROTOTYPES: dict[str, str] = {
    "turismo": (
        "Convocatorias de turismo sostenible, ecoturismo y economía azul: apoyo a hoteles, "
        "viajes, museos y visitantes. Tourism and travel grants, hotelaria e hospitalidade, "
        "blue economy and ecotourism projects."
    ),
    "investigación": (
        "Financiación para investigación científica: ciencia, laboratorio, tesis y becas de "
        "doctorado y posdoctorado para investigadores. Research funding for researchers, scientists "
        "and PhD fellowships; bolsas de pesquisa, doutorado e pós-doutorado."
    ),
    "emprendimiento": (
        "Apoyo a emprendedores: planes de negocio, mipymes, incubadoras, capital semilla y "
        "economía popular. Entrepreneurship support, startups and business plans; empreendedorismo, "
        "incubadoras e cooperativas populares."
    ),
    "innovación": (
        "Ayudas a la innovación y la modernización: industria del futuro, autonomía tecnológica e "
        "inteligencia artificial. Innovation grants and reindustrialization; inovação tecnológica e "
        "indústria do futuro."
    ),
    "transferencia tecnológica": (
        "Convocatorias de transferencia y apropiación tecnológica: extensionismo, extension "
        "tecnológica y llevar tecnologías a las regiones productivas. Technology transfer and "
        "extension programs; transferência e apropriação tecnológica, extensão tecnológica."
    ),
    "educación": (
        "Becas y programas de educación: escuelas, cursos, diplomas, formación docente y "
        "e-learning. Education grants, schools, teachers and scholarships; bolsas de educação, "
        "escolas, cursos e ensino."
    ),
    "salud": (
        "Convocatorias de salud pública: hospitales, atención primaria, enfermería, vacunas y "
        "bienestar. Health services, hospitals, nursing and wellbeing; saúde pública, hospitais, "
        "vacinação e bem-estar."
    ),
    "ambiente": (
        "Fondos de medio ambiente y clima: sostenibilidad, biodiversidad, transición energética y "
        "bosques. Climate action, green funds and sustainability; meio ambiente, sustentabilidade, "
        "biodiversidade e transição energética."
    ),
    "cultura": (
        "Apoyo a la cultura y las artes: música, danza, teatro, cine, patrimonio y festivales. "
        "Culture and arts funding, music and heritage; cultura, música, dança, teatro e patrimônio."
    ),
    "infraestructura": (
        "Obras e infraestructura: construcción, riego, represas, puentes, carreteras, saneamiento "
        "y renovación. Infrastructure works, construction and irrigation; infraestrutura, construção, "
        "irrigação, pontes e saneamento."
    ),
}

# Cosine-similarity floor for accepting the closest prototype.
# Calibrated 2026-10-11 against tests/fixtures/sectores_eval.json with the
# deterministic hashing surrogate stub (lexical lower bound): threshold
# sweep (otros-only fallback) gives 70/90 @0.15, 74/90 @0.30, 77/90 @0.35,
# 78/90 @0.40 == rules baseline (no regression, no fake lift), 78/90 @0.45.
# 0.40 chosen: strictest threshold with zero regression under the stub.
# Re-calibrate server-side with the real embedding model (absolute
# similarities will be higher on semantic matches).
EMBEDDING_SIMILARITY_THRESHOLD = 0.40

# Prototype vectors cached per embed_fn identity (embed_fn is a callable;
# keyed by id() — callers must reuse the same function object).
_PROTOTYPE_VECTORS_CACHE: dict[int, dict[str, list[float]]] = {}


def _cosine(left: list[float], right: list[float]) -> float:
    import math

    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _prototype_vectors(embed_fn: object) -> dict[str, list[float]]:
    key = id(embed_fn)
    cached = _PROTOTYPE_VECTORS_CACHE.get(key)
    if cached is None:
        cached = {sector: list(embed_fn(text)) for sector, text in SECTOR_PROTOTYPES.items()}  # type: ignore[operator]
        _PROTOTYPE_VECTORS_CACHE[key] = cached
    return cached


def classify_by_embedding(
    title: str | None,
    description: str | None,
    embed_fn: object,
    *,
    threshold: float = EMBEDDING_SIMILARITY_THRESHOLD,
) -> tuple[str, float]:
    """Classify (title, description) by cosine similarity to sector prototypes.

    ``embed_fn`` maps text -> vector (injectable; tests use a stub).
    Returns (sector, confidence) with confidence in [0, 1]; below
    ``threshold`` returns ("otros", 0.0). Pure except for ``embed_fn``.
    """
    text = f"{title or ''} {description or ''}".strip()
    if not text:
        return ("otros", 0.0)
    query = list(embed_fn(text))  # type: ignore[operator]
    best_sector = "otros"
    best_similarity = 0.0
    for sector, vector in _prototype_vectors(embed_fn).items():
        similarity = _cosine(query, vector)
        if similarity > best_similarity:
            best_sector = sector
            best_similarity = similarity
    if best_similarity < threshold:
        return ("otros", 0.0)
    return (best_sector, round(min(1.0, best_similarity), 2))


def classify_with_fallback(
    title: str | None,
    description: str | None,
    embed_fn: object,
) -> tuple[str, float, str]:
    """Hybrid router: rules first, embeddings only where rules yields otros.

    Returns (sector, confidence, source) with source in
    {"rules", "embeddings"}. The embedding layer fires ONLY when the
    rules layer returns "otros" (12/90 eval rows) — rerouting low-confidence
    non-otros rules labels was measured to harm accuracy (0.63 vs 0.867
    baseline with the surrogate stub, 2026-10-11), so those stay with rules
    and are T4 (LLM judge) candidates instead. Below the similarity
    threshold the result is ("otros", 0.0, "embeddings").
    """
    sector, confidence = classify_by_rules(title, description)
    if sector != "otros":
        return (sector, confidence, "rules")
    embedded_sector, embedded_confidence = classify_by_embedding(
        title, description, embed_fn
    )
    return (embedded_sector, embedded_confidence, "embeddings")


def classify_by_rules(title: str | None, description: str | None) -> tuple[str, float]:
    """Classify (title, description) into SECTOR_TAXONOMY_V1 by keywords.

    Returns (sector, confidence) with confidence in [0, 1].
    """
    text = f"{_fold(title)} {_fold(description)}".strip()
    best_sector = "otros"
    best_score = 0.0
    for sector in _PATTERNS:
        score = sum(weight for pattern, weight in _PATTERNS[sector] if pattern.search(text))
        if score > best_score:
            best_sector = sector
            best_score = score
    if best_score <= 0.0:
        return ("otros", 0.0)
    return (best_sector, round(min(1.0, best_score / _STRONG_MATCH), 2))


# ── T4 LLM judge layer ───────────────────────────────────────────────
# Final hybrid layer: a Groq chat judge over the CLOSED taxonomy.
# ``llm_client`` is injectable — ``llm_client(system_prompt, user_text)``
# returns ``{"sector": ..., "confidence": ...}`` or ``None`` (abstain).
# Tests pass stubs (zero network); production passes ``groq_sector_judge``
# (temperature 0, JSON-only, graceful abstain when unconfigured).
# Abstain semantics: the judge returning ``None`` (or an invalid payload)
# NEVER regresses the pipeline — the previous layer's label is kept.

SECTOR_JUDGE_SYSTEM_PROMPT = (
    "Eres un clasificador de convocatorias de financiación. "
    "Clasifica el texto en EXACTAMENTE UNA de estas categorías cerradas: "
    + ", ".join(SECTOR_TAXONOMY_V1)
    + ". Devuelve EXCLUSIVAMENTE JSON válido con las claves: "
    'sector (una de las categorías cerradas, texto exacto), '
    "confidence (número 0..1 con tu certeza). "
    "Si el texto no encaja en ninguna categoría, responde "
    '{"sector": "otros", "confidence": 0.0}. '
    "No inventes categorías fuera de la lista."
)

# Rules/embeddings labels below this confidence are sent to the judge
# (the transferencia→emprendimiento miss sits at 0.33). Confident labels
# skip the judge — T3 showed rerouting confident labels harms accuracy.
LLM_JUDGE_LOW_CONFIDENCE_THRESHOLD = 0.5

# Backfill gap-fill contract (single source of truth, mirrored by
# scripts/backfill_sector.py): never reclassify a stored sector with
# confidence >= this unless --force.
SECTOR_HIGH_CONFIDENCE_KEEP = 0.8


def _normalize_judge_sector(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate in SECTOR_TAXONOMY_V1:
        return candidate
    folded = _fold(candidate)
    for sector in SECTOR_TAXONOMY_V1:
        if _fold(sector) == folded:
            return sector
    return None


def _normalize_judge_confidence(value: object) -> float:
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if confidence != confidence:  # NaN
        return 0.0
    return round(min(max(confidence, 0.0), 1.0), 2)


def classify_by_llm_judge(
    text: str,
    llm_client: object,
) -> tuple[str, float]:
    """Ask the injected judge for (sector, confidence); abstain-safe.

    ``llm_client(system_prompt, user_text)`` returns a
    ``{"sector", "confidence"}`` dict or ``None``. Any failure —
    ``None``, exception, unknown sector, bad confidence — degrades to
    ``("otros", 0.0)`` (abstain). Pure except for ``llm_client``.
    """
    if not (text or "").strip() or llm_client is None:
        return ("otros", 0.0)
    try:
        raw = llm_client(SECTOR_JUDGE_SYSTEM_PROMPT, text)  # type: ignore[operator]
    except Exception:
        return ("otros", 0.0)
    if not isinstance(raw, dict):
        return ("otros", 0.0)
    sector = _normalize_judge_sector(raw.get("sector"))
    if sector is None:
        return ("otros", 0.0)
    return (sector, _normalize_judge_confidence(raw.get("confidence")))


async def _call_sector_llm(text: str) -> dict | None:
    """Groq/OpenAI-compatible judge call (READ-ONLY use of ai.py patterns).

    Temperature 0 for determinism, JSON-only response, closed taxonomy
    in the system prompt. Returns ``None`` when unconfigured (local
    provider or missing key) — the pipeline then keeps earlier layers.
    """
    from app.core.config import effective_llm_provider, get_settings
    from app.core.http_client import http_client

    settings = get_settings()
    provider = effective_llm_provider(settings.llm_provider)
    if provider == "local" or not settings.llm_api_key:
        return None
    payload = {
        "model": settings.chat_model or settings.llm_model,
        "messages": [
            {"role": "system", "content": SECTOR_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": text[:8000]},
        ],
        "temperature": 0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }
    client = await http_client()
    response = await client.post(
        f"{settings.llm_api_base.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        import json as _json

        try:
            parsed = _json.loads(content)
        except _json.JSONDecodeError:
            start = content.find("{")
            if start < 0:
                return None
            try:
                parsed, _ = _json.JSONDecoder().raw_decode(content[start:])
            except _json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None
    return None


def groq_sector_judge(system_prompt: str, user_text: str) -> dict | None:
    """Sync production ``llm_client``: Groq judge, abstains when unconfigured.

    ``system_prompt`` is accepted for the injectable-client signature but
    the canonical ``SECTOR_JUDGE_SYSTEM_PROMPT`` is always sent (single
    source of truth). Never raises: transport/validation failures (and
    local/no-key configuration) return ``None``.

    Sync-loop callers only: ``asyncio.run()`` raises inside a running
    event loop, so async callers (e.g. the sector backfill) must use
    ``agroq_sector_judge`` / ``aclassify_sector`` instead.
    """
    del system_prompt
    from app.core.http_client import closing_per_loop_client

    import asyncio

    try:
        return asyncio.run(closing_per_loop_client(_call_sector_llm(user_text)))
    except Exception:
        return None


async def agroq_sector_judge(system_prompt: str, user_text: str) -> dict | None:
    """Async production ``llm_client``: loop-safe twin of ``groq_sector_judge``.

    Awaits the judge coroutine on the caller's loop instead of
    ``asyncio.run()`` — which raises ``RuntimeError`` inside a running
    loop and used to make the judge silently abstain (always ``None``)
    in async callers such as the sector backfill. Same contract:
    canonical prompt always sent, never raises, ``None`` when
    unconfigured or on any failure.
    """
    del system_prompt
    from app.core.http_client import closing_per_loop_client

    try:
        return await closing_per_loop_client(_call_sector_llm(user_text))
    except Exception:
        return None


async def aclassify_by_llm_judge(
    text: str,
    llm_client: object = None,
) -> tuple[str, float]:
    """Async twin of ``classify_by_llm_judge`` — safe inside a running loop.

    ``llm_client`` may be sync or async (awaitables are awaited); ``None``
    selects the production ``agroq_sector_judge`` (abstains when
    unconfigured — zero network). Abstain semantics mirror the sync twin:
    any failure degrades to ``("otros", 0.0)``.
    """
    if not (text or "").strip():
        return ("otros", 0.0)
    client = agroq_sector_judge if llm_client is None else llm_client
    try:
        raw = client(SECTOR_JUDGE_SYSTEM_PROMPT, text)  # type: ignore[operator]
        if inspect.isawaitable(raw):
            raw = await raw
    except Exception:
        return ("otros", 0.0)
    if not isinstance(raw, dict):
        return ("otros", 0.0)
    sector = _normalize_judge_sector(raw.get("sector"))
    if sector is None:
        return ("otros", 0.0)
    return (sector, _normalize_judge_confidence(raw.get("confidence")))


async def aclassify_sector(
    text: str | None,
    *,
    embed_fn: object = None,
    llm_client: object = None,
) -> tuple[str, float, str]:
    """Async hybrid pipeline twin — safe to await inside a running loop.

    Same routing as ``classify_sector`` (rules → otros-only embeddings →
    otros/low-confidence LLM judge). The embedding step runs in a worker
    thread so loop-unsafe sync ``embed_fn`` implementations (``asyncio.run``
    based, e.g. ``build_embedding_sync``) also work from async callers;
    the judge step awaits the coroutine instead of ``asyncio.run``.
    Abstain semantics mirror the sync twin — never regresses below rules.
    """
    combined = (text or "").strip()
    if not combined:
        return ("otros", 0.0, "rules")
    sector, confidence = classify_by_rules(combined, None)
    source = "rules"
    if sector != "otros" and confidence >= LLM_JUDGE_LOW_CONFIDENCE_THRESHOLD:
        return (sector, confidence, source)
    if embed_fn is not None and sector == "otros":
        embedded_sector, embedded_confidence = await asyncio.to_thread(
            classify_by_embedding, combined, None, embed_fn
        )
        if embedded_sector != "otros":
            sector, confidence = embedded_sector, embedded_confidence
            source = "embeddings"
            if confidence >= LLM_JUDGE_LOW_CONFIDENCE_THRESHOLD:
                return (sector, confidence, source)
    judge = await aclassify_by_llm_judge(combined, llm_client)
    if judge != ("otros", 0.0):
        return (judge[0], judge[1], "llm")
    return (sector, confidence, source)


def classify_sector(
    text: str | None,
    *,
    embed_fn: object = None,
    llm_client: object = None,
) -> tuple[str, float, str]:
    """Hybrid pipeline: rules → (otros only) embeddings → (otros or
    low-confidence only) LLM judge.

    Returns (sector, confidence, source) with source in
    {"rules", "embeddings", "llm"}. ``embed_fn`` maps text -> vector
    (when ``None`` the embedding layer is skipped); ``llm_client`` is
    ``(system_prompt, user_text) -> dict | None`` (when ``None`` the
    production ``groq_sector_judge`` is used, which abstains without
    configuration — zero network). A judge abstain keeps the previous
    layer's label and source, so the pipeline never regresses below
    the rules baseline on judge failure.
    """
    combined = (text or "").strip()
    if not combined:
        return ("otros", 0.0, "rules")
    sector, confidence = classify_by_rules(combined, None)
    source = "rules"
    if sector != "otros" and confidence >= LLM_JUDGE_LOW_CONFIDENCE_THRESHOLD:
        return (sector, confidence, source)
    if embed_fn is not None and sector == "otros":
        embedded_sector, embedded_confidence = classify_by_embedding(
            combined, None, embed_fn
        )
        if embedded_sector != "otros":
            sector, confidence = embedded_sector, embedded_confidence
            source = "embeddings"
            if confidence >= LLM_JUDGE_LOW_CONFIDENCE_THRESHOLD:
                return (sector, confidence, source)
    judge = classify_by_llm_judge(
        combined, groq_sector_judge if llm_client is None else llm_client
    )
    if judge != ("otros", 0.0):
        return (judge[0], judge[1], "llm")
    return (sector, confidence, source)
