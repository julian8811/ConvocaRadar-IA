"""Scoring and priority logic for opportunities.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.ai import build_embedding, cosine_similarity
from app.models import Opportunity, OpportunityScore, OrganizationProfile, Priority

# ── Source health score (Change C) ───────────────────────────────────────────


def _normalize_avg_items(avg_items_found: float) -> float:
    """Normalize avg_items_found (0+) to a 0-100 scale.

    Caps at 50 items for a full score. Below that, scales linearly.
    """
    if avg_items_found <= 0:
        return 0.0
    return min(avg_items_found / 50.0 * 100.0, 100.0)


def _normalize_freshness(freshness_days: int | None) -> float:
    """Normalize freshness (days since last success) to a 0-100 scale.

    0-1 days   → 100
    2-7 days   → 80
    8-30 days  → 50
    31-90 days → 20
    >90 days   → 0
    None       → 0
    """
    if freshness_days is None:
        return 0.0
    if freshness_days <= 1:
        return 100.0
    if freshness_days <= 7:
        return 80.0
    if freshness_days <= 30:
        return 50.0
    if freshness_days <= 90:
        return 20.0
    return 0.0


def calculate_source_health_score(
    *,
    success_rate: float,  # 0-100, weight 30%
    avg_items_found: float,  # 0+, weight 20%
    close_date_coverage: float,  # 0-100, weight 15%
    amount_coverage: float,  # 0-100, weight 10%
    url_coverage: float,  # 0-100, weight 10%
    freshness_days: int | None,  # days since last success, weight 10%
    selector_stability: float,  # 0-100, weight 5%
) -> int:
    """Calculate a 0-100 health score for a source.

    Each metric is on a 0-100 scale (or normalized to it). The weighted
    sum produces the final score, clamped to [0, 100] and rounded to int.

    Weights:
    - success_rate: 30%
    - avg_items_found: 20% (normalized from unbounded 0+)
    - close_date_coverage: 15%
    - amount_coverage: 10%
    - url_coverage: 10%
    - freshness_days: 10% (decay curve)
    - selector_stability: 5%
    """
    normalized_avg = _normalize_avg_items(avg_items_found)
    normalized_freshness = _normalize_freshness(freshness_days)

    raw = (
        (success_rate * 0.30)
        + (normalized_avg * 0.20)
        + (close_date_coverage * 0.15)
        + (amount_coverage * 0.10)
        + (url_coverage * 0.10)
        + (normalized_freshness * 0.10)
        + (selector_stability * 0.05)
    )
    return max(0, min(100, round(raw)))


def health_status_for_score(score: int) -> str:
    """Map a 0-100 health score to a status label.

    - 90-100: "healthy"
    - 70-89: "stable"
    - 50-69: "degraded"
    - <50: "critical"
    """
    if score >= 90:
        return "healthy"
    if score >= 70:
        return "stable"
    if score >= 50:
        return "degraded"
    return "critical"


def update_consecutive_empty_runs(items_found: int, current_count: int) -> int:
    """Update consecutive_empty_runs count.

    If items_found == 0, increment. Otherwise reset to 0.
    """
    return current_count + 1 if items_found == 0 else 0


def should_auto_pause(new_count: int) -> bool:
    """Check if the source should be auto-paused (>= 5 consecutive empty runs)."""
    return new_count >= 5


# ── Opportunity scoring (existing) ─────────────────────────────────────────


def priority_for_score(score: float) -> str:
    """Map a numeric score to a priority label.

    Thresholds adjusted for real-world data where most scraped
    opportunities lack funding amounts and detailed eligibility.
    """
    if score >= 75:
        return Priority.high.value
    if score >= 55:
        return Priority.medium.value
    if score >= 30:
        return Priority.low.value
    return Priority.not_recommended.value


def _semantic_score(text: str, profile_text: str) -> float:
    """Compare opportunity text with profile text using embedding similarity.

    Sync fallback — uses local hash only (no event-loop hack). For batched
    remote embeddings use ``batch_semantic_scores``.
    Returns a float in [0, 1] or 0 if empty input.
    """
    if not text.strip() or not profile_text.strip():
        return 0.0
    try:
        from app.core.ai import tokenize_for_embedding
        import hashlib, math
        from app.core.config import get_settings

        settings = get_settings()
        # Remote provider without async context: skip semantic (batch path covers it)
        if settings.llm_api_key and settings.embedding_model:
            from app.core.config import effective_llm_provider
            if effective_llm_provider(settings.llm_provider) != "local":
                return 0.0
        dims = settings.embedding_dimensions or 64

        def _hash_vec(t: str) -> list[float]:
            v = [0.0] * dims
            for tok in tokenize_for_embedding(t[:2000]):
                bucket = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4], "big") % dims
                v[bucket] += 1.0 + min(len(tok), 12) / 12.0
            n = math.sqrt(sum(x * x for x in v))
            return [round(x / n, 6) for x in v] if n else v

        return cosine_similarity(_hash_vec(text), _hash_vec(profile_text))
    except Exception:
        return 0.0


async def batch_semantic_scores(texts: list[str], profile_text: str) -> list[float]:
    """Batch semantic scores via build_embeddings_batch (remote-aware)."""
    if not profile_text.strip() or not texts:
        return [0.0] * len(texts)
    try:
        from app.services.embeddings import build_embeddings_batch

        all_texts = [t[:2000] for t in texts] + [profile_text[:2000]]
        vectors = await build_embeddings_batch(all_texts)
        if len(vectors) != len(all_texts):
            return [0.0] * len(texts)
        prof_vec = vectors[-1]
        return [cosine_similarity(v, prof_vec) for v in vectors[:-1]]
    except Exception:
        return [0.0] * len(texts)


def _compute_score(opportunity: Opportunity, profile: OrganizationProfile) -> dict:
    """Calculate score and reasons WITHOUT touching the DB session.

    Returns ``{"raw": float, "reasons": list[str], "warnings": list[str]}``.
    """
    score = 0.0
    reasons: list[str] = []
    warnings: list[str] = []
    profile_areas = {item.lower() for item in profile.areas_of_interest}
    opp_topics = {item.lower() for item in [*opportunity.categories, *opportunity.topics]}

    # ── Geo proximity: same country + same region bonus ──────────────────
    SAME_REGION = {"LatAm", "Latin America"}
    if opportunity.country == profile.country:
        score += 15
        reasons.append(f"La convocatoria es del mismo país ({profile.country}).")
    elif getattr(opportunity, "region", None) in SAME_REGION and getattr(
        profile, "country", ""
    ) in (profile.country,):
        score += 12
        reasons.append("La convocatoria es de la misma región (LatAm).")
    elif profile.eligible_international:
        score += 10
        reasons.append("La convocatoria es internacional, permitido por el perfil.")
    else:
        score += 5
        warnings.append("La convocatoria puede tener restricciones regionales.")

    eligible = opportunity.eligible_applicants or []
    if eligible:
        opp_types = {item.lower() for item in eligible}
        if profile.organization_type in opp_types:
            score += 20
            reasons.append("Tu tipo de organización está en los beneficiarios elegibles.")
        elif any(profile.organization_type.startswith(t.rstrip("s")) for t in opp_types):
            score += 15
            reasons.append("Tu organización es parcialmente elegible según los requisitos.")
        else:
            score += 5
            warnings.append("El tipo de organización no aparece como beneficiario explícito.")
    else:
        score += 15
        reasons.append("No hay restricciones explícitas de tipo de organización.")

    # ── Category / topic overlap ────────────────────────────────────────
    if profile_areas and opp_topics:
        overlap = profile_areas.intersection(opp_topics)
        if overlap:
            ratio = len(overlap) / max(len(profile_areas), 1)
            if ratio >= 0.5:
                score += 25
                reasons.append(f"Alta coincidencia temática: {', '.join(sorted(overlap))}.")
            elif ratio >= 0.25:
                score += 18
                reasons.append(f"Coincidencia temática media: {', '.join(sorted(overlap))}.")
            else:
                score += 12
                reasons.append(f"Coincidencia temática baja: {', '.join(sorted(overlap))}.")
        else:
            # Fallback: try semantic similarity via embeddings
            semantic = _semantic_score(
                f"{opportunity.title} {opportunity.summary} {opportunity.description}",
                " ".join(profile.areas_of_interest),
            )
            if semantic >= 0.3:
                bonus = min(round(semantic * 25), 18)
                score += bonus
                reasons.append(f"Coincidencia semántica detectada ({bonus} pts).")
            else:
                score += 5
                warnings.append("Las temáticas no coinciden con tus áreas de interés.")
    elif not profile_areas:
        score += 5
        warnings.append("Completa tus áreas de interés en el perfil.")
    else:
        score += 10
        reasons.append("Coincidencia temática base.")

    if opportunity.funding_amount_value:
        if profile.max_funding_amount:
            ratio = opportunity.funding_amount_value / profile.max_funding_amount
            if ratio <= 1.0:
                score += 15 if ratio <= 0.5 else 12
                reasons.append("El monto se ajusta al rango preferido." if ratio <= 1.0 else "")
            else:
                score += 5
                warnings.append("El monto supera el rango preferido.")
        else:
            score += 8
            reasons.append("Monto disponible para revisión.")

    if opportunity.close_date:
        remaining = (opportunity.close_date - datetime.now(UTC).replace(tzinfo=None)).days
        if remaining > 30:
            score += 5
            reasons.append("Hay tiempo suficiente para preparar la postulación.")
        elif remaining > 7:
            score += 3
        elif remaining >= 0:
            warnings.append("Cierra pronto, se requiere acción inmediata.")

    if opportunity.requirements:
        score += 3
        reasons.append("Hay requisitos identificados.")
    if opportunity.documents_required:
        score += 2
        reasons.append("Documentos necesarios identificados.")

    # ── 022 P2: penalize missing data (configurable, bounded) ─────────────
    try:
        from app.core.config import get_settings as _get_s

        _pen_close = int(_get_s().extraction_missing_close_penalty)
        _pen_fund = int(_get_s().extraction_missing_funding_penalty)
    except Exception:
        _pen_close, _pen_fund = 10, 5
    if not opportunity.close_date:
        score -= _pen_close
        warnings.append("Falta fecha de cierre — penalización aplicada.")
    if not opportunity.funding_amount_value:
        score -= _pen_fund
        warnings.append("Falta monto de financiación — penalización aplicada.")
    score = max(0.0, score)

    if score < 40 and not warnings:
        warnings.append("Compatibilidad baja con los datos disponibles.")

    return {"raw": score, "reasons": reasons, "warnings": warnings}


def calculate_score(
    db: Session, opportunity: Opportunity, profile: OrganizationProfile
) -> OpportunityScore:
    """Calculate and persist an OpportunityScore for the given opportunity and profile."""
    score = _compute_score(opportunity, profile)
    result = OpportunityScore(
        opportunity_id=opportunity.id,
        organization_id=profile.organization_id,
        score=min(round(score["raw"], 1), 100),
        priority=priority_for_score(min(score["raw"], 100)),
        reasons=score["reasons"],
        warnings=score["warnings"],
    )
    db.add(result)
    return result
