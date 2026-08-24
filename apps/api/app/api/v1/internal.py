import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.schemas import ConnectorProbeRequest
from app.services import connector_for, is_private_url

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_internal_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    if not hmac.compare_digest(x_internal_api_key or "", get_settings().internal_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal API key"
        )


@router.post("/connectors/probe", dependencies=[Depends(verify_internal_key)])
async def probe_connector(payload: ConnectorProbeRequest) -> dict[str, object]:
    # Reject non-public URLs up-front when the caller supplies one. The
    # endpoint is auth'd by a single API key (not a per-user session), so
    # an attacker who obtains the key, or an operator who fat-fingers a
    # URL, could otherwise pivot the API into probing internal services
    # (cloud metadata endpoints like 169.254.169.254, internal HTTP
    # services, link-local addresses, etc.). When no base_url is sent,
    # the connector uses its configured default — and the same private-IP
    # guard inside the connector itself remains the second line of defense.
    if payload.base_url is not None and is_private_url(payload.base_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url must be a public HTTP/HTTPS URL",
        )
    connector = connector_for(payload.source_key, payload.base_url, payload.source_type)
    stats: dict[str, object] = {
        "source_key": payload.source_key,
        "base_url": payload.base_url,
        "source_type": payload.source_type,
    }
    try:
        raw = await connector.fetch()
        stats["raw_url"] = raw.url
        stats["raw_content_type"] = raw.content_type
        stats["raw_content_length"] = len(raw.content or "")
        candidates = await connector.parse(raw)
        stats["candidates_parsed"] = len(candidates)
        valid = 0
        validation_rejected = 0
        validation_reasons: list[str] = []
        for candidate in candidates:
            result = await connector.validate(candidate)
            if result.ok:
                valid += 1
                continue
            validation_rejected += 1
            if len(validation_reasons) < 5:
                validation_reasons.append(result.reason or "sin razon")
        stats["candidates_valid"] = valid
        stats["validation_rejected"] = validation_rejected
        stats["validation_reasons"] = validation_reasons
        return {"status": "ok", **stats}
    except Exception as exc:
        stats["error"] = str(exc)
        return {"status": "error", **stats}
