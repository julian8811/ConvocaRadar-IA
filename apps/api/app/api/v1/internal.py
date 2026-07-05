import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.schemas import ConnectorProbeRequest
from app.services import connector_for

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_internal_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    if not hmac.compare_digest(x_internal_api_key or "", get_settings().internal_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal API key")


@router.post("/connectors/probe", dependencies=[Depends(verify_internal_key)])
async def probe_connector(payload: ConnectorProbeRequest) -> dict[str, object]:
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
