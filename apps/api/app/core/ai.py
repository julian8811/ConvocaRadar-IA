from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import effective_llm_provider, get_settings
from app.core.http_client import http_client
from app.schemas import AiOpportunityExtract

MODEL_VERSION = "gemini-vertex" if get_settings().llm_api_key and get_settings().embedding_model else "local-heuristic-v2"
LOCAL_EMBEDDING_MODEL_VERSION = "local-hash-embeddings-v2"
EMBEDDING_MODEL_VERSION = MODEL_VERSION
PROMPT_VERSION = "structured-extraction-v3"

COUNTRY_RULES: list[tuple[str, str]] = [
    ("colombia", "Colombia"),
    ("united states", "United States"),
    ("usa", "United States"),
    ("u.s.", "United States"),
    ("european union", "European Union"),
    ("europa", "European Union"),
    ("chile", "Chile"),
    ("peru", "Peru"),
    ("mexico", "Mexico"),
    ("brazil", "Brazil"),
    ("argentina", "Argentina"),
    ("spain", "Spain"),
]

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("innovation", ["innovation", "innovacion", "startup", "tech", "technology"]),
    ("research", ["research", "investigacion", "science", "ciencia"]),
    ("cooperation", ["cooperation", "cooperacion", "partnership", "collaboration"]),
    ("education", ["education", "learning", "beca", "scholarship", "students"]),
    ("federal funding", ["grants.gov", "federal", "funding", "grant", "subsidy"]),
]

REQUIREMENT_PATTERNS = [
    r"\bmust\b.*",
    r"\brequires?\b.*",
    r"\brequisito[s]?\b.*",
    r"\bdebe[n]?\b.*",
]

DOCUMENT_PATTERNS = [
    r"\bdocument[s]?\b.*",
    r"\bannex(?:e|es)?\b.*",
    r"\banexo[s]?\b.*",
    r"\bproposal\b.*",
    r"\bform\b.*",
]

DATE_PATTERNS = [
    r"\b(\d{4}-\d{2}-\d{2})\b",
    r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
    r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\b",
]


@dataclass
class AIExtraction:
    data: dict[str, Any]
    confidence: float
    provider: str


def normalize_text(value: str | None) -> str:
    text = unescape(value or "")
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(
        r"(?im)^\s*(?:color|background-color|font-weight|font-size|display|justify-content|text-decoration|margin|padding)\s*:\s*[^;]+;?\s*$",
        " ",
        text,
    )
    text = re.sub(r"(?im)^\s*[.#][\w-]+\s*\{[^}]*\}\s*$", " ", text)
    text = re.sub(r"(?im)^\s*\{[^}]*\}\s*$", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_for_rules(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_text(value))
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return stripped.lower()


def _split_lines(text: str) -> list[str]:
    return [normalize_text(line) for line in text.splitlines() if normalize_text(line)]


def _looks_like_noise_line(value: str) -> bool:
    lowered = _normalize_for_rules(value)
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or any(
            marker in lowered
            for marker in (
                "color:",
                "background-color:",
                "font-weight:",
                "font-size:",
                "display:",
                "justify-content:",
                "text-decoration:",
                "budgetyearscolumns",
                "plannedopeningdate",
                "deadlinedate",
                "expectedgrants",
            )
        )
        or "{" in value
        or "}" in value
    )


def _extract_keyword_matches(text: str) -> list[str]:
    lowered = _normalize_for_rules(text)
    matches: list[str] = []
    for category, keywords in CATEGORY_RULES:
        if any(_normalize_for_rules(keyword) in lowered for keyword in keywords):
            matches.append(category)
    return matches


def infer_language(text: str, fallback: str = "en") -> str:
    normalized = _normalize_for_rules(text)
    if not normalized:
        return fallback
    spanish_signals = sum(
        1
        for token in [" convocatoria ", " requisitos ", " cierre ", " financi", " innovacion ", " investig", " beca ", " postulacion ", " elegible "]
        if token in f" {normalized} "
    )
    english_signals = sum(
        1
        for token in [" call ", " funding ", " deadline ", " requirements ", " eligible ", " scholarship ", " innovation ", " research ", " application "]
        if token in f" {normalized} "
    )
    if spanish_signals > english_signals:
        return "es"
    if english_signals > spanish_signals:
        return "en"
    return fallback


def _extract_country(text: str) -> str:
    lowered = _normalize_for_rules(text)
    for needle, country in COUNTRY_RULES:
        if _normalize_for_rules(needle) in lowered:
            return country
    return "Por validar"


def _extract_title(text: str) -> str:
    lines = _split_lines(text)
    if lines:
        for line in lines[:8]:
            if 8 <= len(line) <= 160 and not _looks_like_noise_line(line):
                return line
    for pattern in [r"^#{1,3}\s+(.+)$", r"^[A-Z][^\n]{10,150}$"]:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            candidate = normalize_text(match.group(1) if match.lastindex else match.group(0))
            if candidate and not _looks_like_noise_line(candidate):
                return candidate[:160]
    sentences = re.split(r"(?<=[.!?])\s+", normalize_text(text))
    for sentence in sentences:
        candidate = normalize_text(sentence)
        if candidate and not _looks_like_noise_line(candidate):
            return candidate[:160]
    return "Convocatoria detectada"


def _extract_date(text: str) -> str | None:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _extract_amount(text: str) -> str | None:
    amount_patterns = [
        r"USD\s?[\d.,]+(?:\s?(?:million|m|k))?",
        r"EUR\s?[\d.,]+(?:\s?(?:million|m|k))?",
        r"COP\s?[\d.,]+",
        r"\$\s?[\d.,]+(?:\s?(?:COP|USD|EUR))?",
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(0))
    return None


def _extract_bullets(text: str, patterns: list[str], *, limit: int = 5) -> list[str]:
    lines = _split_lines(text)
    items: list[str] = []
    for line in lines:
        lowered = _normalize_for_rules(line)
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns):
            cleaned = re.sub(r"^[•\-\*]\s*", "", line).strip(" :-")
            if cleaned and cleaned not in items:
                items.append(cleaned)
        if len(items) >= limit:
            break
    return items


def _extract_summary(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "Resumen pendiente de contenido suficiente."
    sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", normalized) if sentence and not _looks_like_noise_line(sentence)]
    if not sentences:
        return "Resumen pendiente de contenido suficiente."
    return " ".join(sentences[:3])[:600]


def _risk_flags(text: str, confidence: float) -> list[str]:
    flags: list[str] = []
    lowered = _normalize_for_rules(text)
    if "deadline" not in lowered and "cierre" not in lowered and "close" not in lowered:
        flags.append("No se detectó una fecha de cierre clara.")
    if confidence < 0.7:
        flags.append("La extracción automática tiene confianza media.")
    if "manual review" in lowered or "revisar manualmente" in lowered:
        flags.append("La convocatoria requiere revisión manual.")
    if "eligibility" in lowered or "elegible" in lowered:
        flags.append("Se detectan restricciones de elegibilidad.")
    return flags or ["Revisión automática pendiente."]


def _recommendation(confidence: float, categories: list[str], risk_flags: list[str]) -> tuple[str, str]:
    if confidence >= 0.82 and "research" in categories:
        return "Alta prioridad para revisión.", "high"
    if confidence >= 0.68:
        if risk_flags:
            return "Revisar manualmente antes de aplicar.", "medium"
        return "Compatible con revisión rápida.", "medium"
    if confidence >= 0.45:
        return "Guardar para seguimiento y depuración manual.", "low"
    return "Descartar o validar con la fuente oficial.", "not_recommended"


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in (part.strip() for part in re.split(r"[;,|]\s*", value)) if item]
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if item is None:
                continue
            text = normalize_text(str(item))
            if text and text not in items:
                items.append(text)
        return items
    return [normalize_text(str(value))]


def _normalize_remote_extraction(payload: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(payload)
    if "category" not in mapped and "categories" in mapped:
        mapped["category"] = mapped.pop("categories")
    if "risks" not in mapped and "risk_flags" in mapped:
        mapped["risks"] = mapped.pop("risk_flags")
    if "documents_required" not in mapped and "documents" in mapped:
        mapped["documents_required"] = mapped.pop("documents")
    if "matched_keywords" not in mapped and "keywords" in mapped:
        mapped["matched_keywords"] = mapped.pop("keywords")
    if "confidence" in mapped:
        try:
            mapped["confidence"] = round(min(max(float(mapped["confidence"]), 0.0), 1.0), 2)
        except (TypeError, ValueError):
            mapped["confidence"] = 0.0
    mapped["title"] = normalize_text(str(mapped.get("title") or "")) or "Convocatoria detectada"
    mapped["entity"] = normalize_text(str(mapped.get("entity") or "")) or "Entidad por validar"
    mapped["country"] = normalize_text(str(mapped.get("country") or "")) or "Por validar"
    mapped["summary"] = normalize_text(str(mapped.get("summary") or ""))
    mapped["recommendation"] = normalize_text(str(mapped.get("recommendation") or ""))
    mapped["status"] = normalize_text(str(mapped.get("status") or "")) or "unknown"
    mapped["category"] = _coerce_text_list(mapped.get("category"))
    mapped["requirements"] = _coerce_text_list(mapped.get("requirements"))
    mapped["documents_required"] = _coerce_text_list(mapped.get("documents_required"))
    mapped["risks"] = _coerce_text_list(mapped.get("risks"))
    mapped["matched_keywords"] = _coerce_text_list(mapped.get("matched_keywords"))
    mapped["extraction_notes"] = _coerce_text_list(mapped.get("extraction_notes"))
    mapped["priority"] = normalize_text(str(mapped.get("priority") or "")) or "medium"
    mapped["risk_level"] = normalize_text(str(mapped.get("risk_level") or "")) or "medium"
    mapped["model_version"] = normalize_text(str(mapped.get("model_version") or MODEL_VERSION))
    mapped["provider"] = normalize_text(str(mapped.get("provider") or get_settings().llm_provider))
    mapped["prompt_version"] = normalize_text(str(mapped.get("prompt_version") or PROMPT_VERSION))
    mapped["extraction_strategy"] = normalize_text(str(mapped.get("extraction_strategy") or "remote"))
    return mapped


async def _call_llm(text: str) -> dict[str, Any] | None:
    settings = get_settings()
    provider = effective_llm_provider(settings.llm_provider)
    if provider == "local" or not settings.llm_api_key:
        return None

    system_prompt = (
        "Eres un extractor estructurado para convocatorias de financiacion. "
        f"Devuelve exclusivamente JSON valido usando el esquema version {PROMPT_VERSION}. "
        "Campos obligatorios: title, entity, country, category, status, close_date, requirements, documents_required, "
        "summary, risks, recommendation, confidence, matched_keywords, risk_level, priority, extraction_notes. "
        "Incluye prompt_version, model_version, provider y extraction_strategy si puedes."
    )
    payload = {
        "model": settings.chat_model or settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text[:12000]},
        ],
        "temperature": 0.1,
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
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def build_local_extraction(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    title = _extract_title(text)
    categories = _extract_keyword_matches(normalized) or ["innovation"]
    requirements = _extract_bullets(normalized, REQUIREMENT_PATTERNS)
    documents_required = _extract_bullets(normalized, DOCUMENT_PATTERNS)
    country = _extract_country(normalized)
    amount = _extract_amount(normalized)
    close_date = _extract_date(normalized)
    confidence = 0.52
    if len(normalized) > 200:
        confidence += 0.08
    if categories:
        confidence += min(len(categories) * 0.08, 0.24)
    if requirements:
        confidence += 0.08
    if documents_required:
        confidence += 0.08
    if country != "Por validar":
        confidence += 0.06
    confidence = round(min(confidence, 0.95), 2)
    risk_flags = _risk_flags(normalized, confidence)
    recommendation, priority = _recommendation(confidence, categories, risk_flags)
    language = infer_language(normalized)
    extraction_notes = [
        "Structured extraction generated locally.",
        f"Matched keywords: {', '.join(categories)}" if categories else "No category keywords detected.",
        f"Confidence basis: {len(normalized)} chars, {len(requirements)} requirements, {len(documents_required)} documents.",
    ]
    return {
        "title": title,
        "entity": "Entidad por validar",
        "country": country,
        "category": categories[:5],
        "status": "unknown" if close_date is None else "open",
        "close_date": close_date,
        "requirements": requirements[:5] or ["Validar requisitos en la fuente oficial"],
        "documents_required": documents_required[:5] or ["Documento oficial de la convocatoria"],
        "summary": _extract_summary(normalized),
        "risks": risk_flags,
        "recommendation": recommendation,
        "confidence": confidence,
        "matched_keywords": categories[:8],
        "risk_level": "medium" if risk_flags else "low",
        "priority": priority,
        "funding_amount_raw": amount,
        "extraction_notes": extraction_notes,
        "model_version": MODEL_VERSION,
        "provider": "local",
        "prompt_version": PROMPT_VERSION,
        "extraction_strategy": "local-heuristic",
        "language": language,
    }


async def extract_opportunity_structured(text: str) -> AIExtraction:
    remote = await _call_llm(text)
    if remote:
        normalized = build_local_extraction(text)
        merged = {**normalized, **_normalize_remote_extraction(remote)}
        merged.setdefault("model_version", MODEL_VERSION)
        merged.setdefault("provider", get_settings().llm_provider)
        merged.setdefault("prompt_version", PROMPT_VERSION)
        merged.setdefault("extraction_strategy", "remote-llm")
        confidence = float(merged.get("confidence") or normalized["confidence"])
        merged["confidence"] = round(min(max(confidence, 0.0), 1.0), 2)
        if not merged.get("matched_keywords"):
            merged["matched_keywords"] = normalized["matched_keywords"]
        if not merged.get("risk_level"):
            merged["risk_level"] = normalized["risk_level"]
        if not merged.get("priority"):
            merged["priority"] = normalized["priority"]
        if not merged.get("summary"):
            merged["summary"] = normalized["summary"]
        try:
            validated = AiOpportunityExtract.model_validate(merged).model_dump()
        except ValidationError:
            return AIExtraction(data=normalized, confidence=normalized["confidence"], provider="local")
        validated.setdefault("language", normalized["language"])
        validated.setdefault("model_version", MODEL_VERSION)
        validated.setdefault("provider", get_settings().llm_provider)
        validated.setdefault("prompt_version", PROMPT_VERSION)
        validated.setdefault("extraction_strategy", "remote-llm")
        return AIExtraction(data={**merged, **validated}, confidence=merged["confidence"], provider=str(merged["provider"]))
    local = build_local_extraction(text)
    return AIExtraction(data=local, confidence=local["confidence"], provider="local")


def summarize_opportunity_text(text: str) -> str:
    extraction = build_local_extraction(text)
    return str(extraction["summary"])


def tokenize_for_embedding(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", _normalize_for_rules(text)) if token]


def embedding_model_version() -> str:
    settings = get_settings()
    provider = effective_llm_provider(settings.llm_provider)
    if provider == "openai" and settings.llm_api_key and settings.embedding_model:
        return f"openai-{settings.embedding_model}-d{settings.embedding_dimensions}"
    return LOCAL_EMBEDDING_MODEL_VERSION


async def _call_openai_embedding(text: str, *, dimensions: int) -> list[float] | None:
    settings = get_settings()
    if effective_llm_provider(settings.llm_provider) != "openai" or not settings.llm_api_key or not settings.embedding_model:
        return None
    payload = {
        "model": settings.embedding_model,
        "input": text[:8000],
        "dimensions": dimensions,
    }
    client = await http_client()
    response = await client.post(
        f"{settings.llm_api_base.rstrip('/')}/embeddings",
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("data") or []
    if not rows:
        return None
    vector = rows[0].get("embedding")
    if not isinstance(vector, list):
        return None
    return [round(float(item), 6) for item in vector]


async def build_embedding(text: str, *, dimensions: int | None = None) -> list[float]:
    settings = get_settings()
    target_dimensions = dimensions or settings.embedding_dimensions or 64
    if effective_llm_provider(settings.llm_provider) == "openai" and settings.llm_api_key and settings.embedding_model:
        try:
            result = await _call_openai_embedding(text, dimensions=target_dimensions)
            if result:
                return result
        except Exception:
            pass
    vector = [0.0] * target_dimensions
    tokens = tokenize_for_embedding(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % target_dimensions
        weight = 1.0 + min(len(token), 12) / 12.0
        vector[bucket] += weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def build_embedding_sync(text: str, *, dimensions: int | None = None) -> list[float]:
    return asyncio.run(build_embedding(text, dimensions=dimensions))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return round(dot / (left_norm * right_norm), 4)


def compose_embedding_text(
    title: str,
    summary: str,
    raw_text: str,
    categories: list[str] | None = None,
    topics: list[str] | None = None,
) -> str:
    parts = [title, summary, raw_text]
    if categories:
        parts.append("Categories: " + ", ".join(categories))
    if topics:
        parts.append("Topics: " + ", ".join(topics))
    return "\n".join(part for part in parts if part).strip()
