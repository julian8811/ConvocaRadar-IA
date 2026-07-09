import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_profile, get_current_user
from app.core.config import get_settings
from app.core.storage import delete_object, put_bytes, read_bytes
from app.db.session import get_db
from app.models import Opportunity, OpportunityDocument, OpportunityScore, Organization, OrganizationProfile, User
from app.schemas import (
    OpportunityDocumentRead,
    OpportunityList,
    OpportunityRead,
    OpportunitySemanticList,
    OpportunityUpdate,
    ScoreRead,
)
from app.services import (
    audit,
    build_opportunity_query,
    calculate_score,
    count_query,
    export_csv,
    export_xlsx,
    is_noise_payload,
    reanalyze_opportunity,
    semantic_search_opportunities,
    upsert_opportunity_embedding,
)

router = APIRouter()

ALLOWED_UPLOAD_TYPES = {
    "application/pdf",
    "text/html",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _opportunity_scope(organization_id: str):
    return (Opportunity.organization_id == organization_id) | (Opportunity.organization_id.is_(None))


def _get_opportunity_for_org(db: Session, opportunity_id: str, organization: Organization) -> Opportunity:
    opportunity = db.scalar(select(Opportunity).where(Opportunity.id == opportunity_id, _opportunity_scope(organization.id)))
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if is_noise_payload(opportunity.title, opportunity.summary, opportunity.raw_text):
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity


def _get_document_for_org(db: Session, document_id: str, organization: Organization) -> OpportunityDocument:
    document = db.scalar(
        select(OpportunityDocument)
        .join(Opportunity, Opportunity.id == OpportunityDocument.opportunity_id)
        .where(OpportunityDocument.id == document_id, _opportunity_scope(organization.id))
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/opportunities", response_model=OpportunityList)
def list_opportunities(
    country: str | None = None,
    category: str | None = None,
    status: str | None = None,
    source_id: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    close_date_from: str | None = None,
    close_date_to: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
    ) -> OpportunityList:
    stmt = build_opportunity_query(
        organization.id,
        country=country,
        category=category,
        status=status,
        source_id=source_id,
        priority=priority,
        search=search,
        close_date_from=close_date_from,
        close_date_to=close_date_to,
        min_amount=min_amount,
        max_amount=max_amount,
    )
    total = count_query(db, stmt)
    items = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return OpportunityList(items=items, total=total, page=page, page_size=page_size)


@router.get("/opportunities/semantic-search", response_model=OpportunitySemanticList)
def semantic_search(
    query: str = Query(min_length=2),
    limit: int = Query(default=10, ge=1, le=25),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> OpportunitySemanticList:
    matches = semantic_search_opportunities(db, organization.id, query, limit=limit)
    return OpportunitySemanticList(
        query=query,
        items=[{"opportunity": opportunity, "similarity": similarity} for opportunity, similarity in matches],
    )


@router.get("/opportunities/export")
def export_opportunities(
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export all opportunities visible to the organization as CSV or XLSX.

    Returns a downloadable file with columns: title, entity, country, status,
    close_date, funding_amount, official_url.
    """
    scope = _opportunity_scope(organization.id)
    opportunities = list(db.scalars(select(Opportunity).where(scope).order_by(Opportunity.created_at.desc())))

    if format == "xlsx":
        content = export_xlsx(opportunities)
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=convocatorias_{datetime.now(UTC).date().isoformat()}.xlsx"},
        )
    content = export_csv(opportunities)
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=convocatorias_{datetime.now(UTC).date().isoformat()}.csv"},
    )


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(
    opportunity_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Opportunity:
    return _get_opportunity_for_org(db, opportunity_id, organization)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdate,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Opportunity:
    opportunity = _get_opportunity_for_org(db, opportunity_id, organization)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(opportunity, key, value)
    upsert_opportunity_embedding(db, opportunity)
    profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == organization.id))
    if profile:
        calculate_score(db, opportunity, profile)
    audit(db, "update_opportunity", "opportunity", user, opportunity.id)
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.post("/opportunities/{opportunity_id}/favorite", response_model=OpportunityRead)
def favorite_opportunity(
    opportunity_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Opportunity:
    opportunity = _get_opportunity_for_org(db, opportunity_id, organization)
    opportunity.is_favorite = True
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.delete("/opportunities/{opportunity_id}/favorite", response_model=OpportunityRead)
def unfavorite_opportunity(
    opportunity_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Opportunity:
    opportunity = _get_opportunity_for_org(db, opportunity_id, organization)
    opportunity.is_favorite = False
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.post("/opportunities/{opportunity_id}/status", response_model=OpportunityRead)
def set_user_status(
    opportunity_id: str,
    status: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Opportunity:
    opportunity = _get_opportunity_for_org(db, opportunity_id, organization)
    opportunity.user_status = status
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.get("/opportunities/{opportunity_id}/scores", response_model=list[ScoreRead])
def get_scores(
    opportunity_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[OpportunityScore]:
    _get_opportunity_for_org(db, opportunity_id, organization)
    return list(
        db.scalars(
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
            .order_by(OpportunityScore.calculated_at.desc())
        )
    )


@router.post("/opportunities/{opportunity_id}/scores", response_model=ScoreRead)
def score_opportunity(
    opportunity_id: str,
    profile: OrganizationProfile = Depends(get_current_profile),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> OpportunityScore:
    opportunity = _get_opportunity_for_org(db, opportunity_id, organization)
    score = calculate_score(db, opportunity, profile)
    db.commit()
    db.refresh(score)
    return score


@router.post("/opportunities/{opportunity_id}/reanalyze", response_model=OpportunityRead)
def reanalyze_single_opportunity(
    opportunity_id: str,
    force: bool = False,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    profile: OrganizationProfile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> Opportunity:
    opportunity = _get_opportunity_for_org(db, opportunity_id, organization)
    reanalyze_opportunity(db, opportunity, force=force)
    calculate_score(db, opportunity, profile)
    audit(db, "reanalyze_opportunity", "opportunity", user, opportunity.id)
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.post("/opportunities/reanalyze-all")
def reanalyze_all_opportunities(
    force: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    profile: OrganizationProfile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    opportunities = list(
        db.scalars(
            select(Opportunity)
            .where(_opportunity_scope(organization.id))
            .order_by(Opportunity.updated_at.desc())
            .limit(limit)
        )
    )
    processed = 0
    updated = 0
    rescored = 0
    for opportunity in opportunities:
        processed += 1
        before_summary = opportunity.summary
        reanalyze_opportunity(db, opportunity, force=force)
        calculate_score(db, opportunity, profile)
        if opportunity.summary != before_summary:
            updated += 1
        rescored += 1
    audit(db, "reanalyze_all_opportunities", "opportunity", user, None)
    db.commit()
    return {"processed": processed, "updated": updated, "rescored": rescored}


@router.get("/opportunities/{opportunity_id}/documents", response_model=list[OpportunityDocumentRead])
def list_documents(
    opportunity_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[OpportunityDocument]:
    _get_opportunity_for_org(db, opportunity_id, organization)
    return list(
        db.scalars(
            select(OpportunityDocument)
            .where(OpportunityDocument.opportunity_id == opportunity_id)
            .order_by(OpportunityDocument.created_at.desc())
        )
    )


@router.post("/opportunities/{opportunity_id}/documents", response_model=OpportunityDocumentRead)
async def upload_document(
    opportunity_id: str,
    file: UploadFile = File(...),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpportunityDocument:
    _get_opportunity_for_org(db, opportunity_id, organization)
    settings = get_settings()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File is too large")
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail="File type is not allowed")

    checksum = hashlib.sha256(content).hexdigest()
    safe_name = Path(file.filename or "document").name
    storage_key = f"opportunities/{opportunity_id}/{checksum[:16]}-{safe_name}"
    stored = put_bytes(storage_key, content, content_type)

    document = OpportunityDocument(
        opportunity_id=opportunity_id,
        file_name=safe_name,
        file_type=content_type,
        storage_path=stored.storage_path,
        checksum=checksum,
        text_content=content[:5000].decode("utf-8", errors="ignore") if content_type.startswith("text/") else "",
    )
    db.add(document)
    db.flush()
    audit(db, "upload_document", "opportunity_document", user, document.id)
    db.commit()
    db.refresh(document)
    return document


@router.get("/opportunity-documents/{document_id}/download")
def download_document(
    document_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Response:
    document = _get_document_for_org(db, document_id, organization)
    if not document.storage_path:
        raise HTTPException(status_code=404, detail="Stored file not found")
    content = read_bytes(document.storage_path)
    return Response(
        content,
        media_type=document.file_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )


@router.delete("/opportunity-documents/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    document = _get_document_for_org(db, document_id, organization)
    if document.storage_path:
        delete_object(document.storage_path)
    audit(db, "delete_document", "opportunity_document", user, document.id)
    db.delete(document)
    db.commit()
