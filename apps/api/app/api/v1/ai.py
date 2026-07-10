from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User
from app.schemas import AiOpportunityExtract, AiTextRequest
from app.services import create_ai_extraction, summarize_text

router = APIRouter(prefix="/ai")


@router.post("/extract-opportunity", response_model=AiOpportunityExtract)
async def extract_opportunity(payload: AiTextRequest, user: User = Depends(get_current_user)) -> dict[str, object]:
    return await create_ai_extraction(payload.text)


@router.post("/classify-opportunity")
async def classify_opportunity(payload: AiTextRequest, user: User = Depends(get_current_user)) -> dict[str, object]:
    extraction = await create_ai_extraction(payload.text)
    return {
        "category": extraction["category"],
        "confidence": extraction["confidence"],
        "matched_keywords": extraction.get("matched_keywords", []),
        "priority": extraction.get("priority", "medium"),
    }


@router.post("/score-opportunity")
async def score_opportunity(payload: AiTextRequest, user: User = Depends(get_current_user)) -> dict[str, object]:
    extraction = await create_ai_extraction(payload.text)
    score = round(float(extraction.get("confidence", 0.5)) * 100)
    return {
        "score": score,
        "priority": extraction.get("priority", "medium"),
        "reasons": [
            f"Categorías detectadas: {', '.join(extraction.get('category', [])) or 'sin coincidencia'}",
            f"Confianza estructurada: {extraction.get('confidence', 0.5)}",
        ],
        "warnings": extraction.get("risks", []),
        "model_version": extraction.get("model_version", "local-heuristic-v2"),
    }


@router.post("/summarize-opportunity")
def summarize_opportunity(payload: AiTextRequest, user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"summary": summarize_text(payload.text)}


@router.post("/generate-report-summary")
def generate_report_summary(user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"summary": "Reporte ejecutivo generado con oportunidades priorizadas por compatibilidad."}
