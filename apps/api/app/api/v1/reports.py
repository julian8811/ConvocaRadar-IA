from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.core.storage import delete_object, put_bytes
from app.db.session import get_db
from app.models import Opportunity, Organization, Report, User
from app.schemas import ReportCreate, ReportRead
from app.services import audit, build_opportunity_query, export_csv, export_pdf, export_xlsx, generate_report_html

router = APIRouter()


def _report_opportunities(db: Session, report: Report) -> list[Opportunity]:
    filters = report.filters or {}
    stmt = build_opportunity_query(
        report.organization_id,
        country=filters.get("country") or None,
        category=filters.get("category") or None,
        status=filters.get("status") or None,
        source_id=filters.get("source_id") or None,
        priority=filters.get("priority") or None,
        search=filters.get("search") or None,
    )
    return list(db.scalars(stmt.limit(200)))


def _safe_report_name(title: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in title).strip("-")
    return cleaned[:48] or "report"


def _store_report_artifact(db: Session, report: Report, content: bytes, media_type: str, extension: str) -> None:
    key = f"reports/{report.organization_id}/{report.id}/{_safe_report_name(report.title)}.{extension}"
    stored = put_bytes(key, content, media_type)
    report.file_path = stored.storage_path
    db.commit()


@router.get("/reports", response_model=list[ReportRead])
def list_reports(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[Report]:
    return list(db.scalars(select(Report).where(Report.organization_id == organization.id).order_by(Report.created_at.desc())))


@router.post("/reports", response_model=ReportRead)
def create_report(
    payload: ReportCreate,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Report:
    filters = payload.filters or {}
    stmt = build_opportunity_query(
        organization.id,
        country=filters.get("country") or None,
        category=filters.get("category") or None,
        status=filters.get("status") or None,
        source_id=filters.get("source_id") or None,
        priority=filters.get("priority") or None,
        search=filters.get("search") or None,
    )
    opportunities = list(
        db.scalars(stmt.limit(200))
    )
    html = generate_report_html(payload.title, organization, opportunities)
    report = Report(
        organization_id=organization.id,
        title=payload.title,
        report_type=payload.report_type,
        format=payload.format,
        html_content=html,
        filters=payload.filters,
        generated_by=user.id,
    )
    db.add(report)
    db.flush()
    audit(db, "create_report", "report", user, report.id)
    db.commit()
    db.refresh(report)
    return report


@router.get("/reports/{report_id}", response_model=ReportRead)
def get_report(
    report_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Report:
    report = db.scalar(select(Report).where(Report.id == report_id, Report.organization_id == organization.id))
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(
    report_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    report = db.scalar(select(Report).where(Report.id == report_id, Report.organization_id == organization.id))
    if report:
        if report.file_path:
            delete_object(report.file_path)
        audit(db, "delete_report", "report", user, report.id)
        db.delete(report)
        db.commit()


@router.post("/reports/{report_id}/regenerate", response_model=ReportRead)
def regenerate_report(
    report_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Report:
    report = db.scalar(select(Report).where(Report.id == report_id, Report.organization_id == organization.id))
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    opportunities = _report_opportunities(db, report)
    report.html_content = generate_report_html(report.title, organization, opportunities)
    if report.file_path:
        delete_object(report.file_path)
        report.file_path = None
    audit(db, "regenerate_report", "report", user, report.id)
    db.commit()
    db.refresh(report)
    return report


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Response:
    report = db.scalar(select(Report).where(Report.id == report_id, Report.organization_id == organization.id))
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    safe_name = _safe_report_name(report.title)
    if report.format == "csv":
        opportunities = _report_opportunities(db, report)
        content = export_csv(opportunities)
        _store_report_artifact(db, report, content.encode("utf-8"), "text/csv", "csv")
        return Response(content, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={safe_name}.csv"})
    if report.format == "xlsx":
        opportunities = _report_opportunities(db, report)
        content = export_xlsx(opportunities)
        _store_report_artifact(
            db,
            report,
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={safe_name}.xlsx"},
        )
    if report.format == "pdf":
        opportunities = _report_opportunities(db, report)
        content = export_pdf(report.title, organization, opportunities)
        _store_report_artifact(db, report, content, "application/pdf", "pdf")
        return Response(
            content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={safe_name}.pdf"},
        )
    _store_report_artifact(db, report, report.html_content.encode("utf-8"), "text/html", "html")
    return Response(
        report.html_content,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename={safe_name}.html"},
    )
