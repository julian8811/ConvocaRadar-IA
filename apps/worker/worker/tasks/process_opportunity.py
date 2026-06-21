from worker.app import celery_app


def _lead_summary(text: str, *, limit: int = 280) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "Resumen generado a partir de metadatos incompletos."
    sentences = [sentence.strip() for sentence in normalized.split(". ") if sentence.strip()]
    summary = ". ".join(sentences[:2]).strip() if sentences else normalized
    return summary[:limit].rstrip(" .") + ("..." if len(summary) > limit else "")


def _risk_flags(candidate: dict[str, object], text: str) -> list[str]:
    flags: list[str] = []
    lowered = text.lower()
    if not candidate.get("close_date") and "deadline" not in lowered and "cierre" not in lowered:
        flags.append("No se detecto una fecha de cierre clara.")
    if not candidate.get("funding_amount_raw") and not candidate.get("funding_amount_value"):
        flags.append("El monto no fue identificado con precision.")
    if float(candidate.get("confidence_score") or 0.0) < 0.7:
        flags.append("La extraccion automatica aun requiere revision.")
    if not candidate.get("requirements"):
        flags.append("No se detectaron requisitos estructurados.")
    return flags or ["Revision automatica completada sin incidencias obvias."]


@celery_app.task(name="process_opportunity")
def process_opportunity(candidate: dict[str, object]) -> dict[str, object]:
    text = str(candidate.get("raw_text") or candidate.get("summary") or "")
    candidate["summary"] = str(candidate.get("summary") or _lead_summary(text))
    candidate["risk_flags"] = candidate.get("risk_flags") or _risk_flags(candidate, text)
    candidate["confidence_score"] = float(candidate.get("confidence_score") or 0.5)
    return candidate
