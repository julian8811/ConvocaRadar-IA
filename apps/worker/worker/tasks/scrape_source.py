import asyncio
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from worker.app import celery_app
from worker.config import get_settings
from worker.connectors.factory import connector_for


def _complete_source_run(source_run_id: str, payload: dict[str, object]) -> None:
    settings = get_settings()
    url = f"{settings.backend_url.rstrip('/')}/api/v1/internal/source-runs/{source_run_id}/complete"
    response = httpx.post(url, json=payload, headers={"X-Internal-API-Key": settings.internal_api_key}, timeout=60)
    response.raise_for_status()


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, TimeoutError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=6),
    reraise=True,
)
async def _fetch_candidates(connector):
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    return raw, candidates


@celery_app.task(name="scrape_source")
def scrape_source(
    source_key: str,
    base_url: str | None = None,
    source_type: str | None = None,
    source_run_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    if base_url:
        from worker.connectors.common import _is_private_host

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or _is_private_host(parsed.hostname or ""):
            raise ValueError(f"Blocked unsafe source URL: {base_url}")

    async def run() -> dict[str, object]:
        connector = connector_for(source_key, base_url, source_type)
        raw, candidates = await _fetch_candidates(connector)
        valid = []
        invalid = 0
        logs = [
            {
                "level": "info",
                "message": "Worker connector executed",
                "source_key": source_key,
                "source_type": source_type,
                "base_url": base_url,
            },
        ]
        for candidate in candidates:
            result = await connector.validate(candidate)
            if result.ok:
                valid.append(candidate.__dict__)
                continue
            invalid += 1
            logs.append(
                {
                    "level": "warning",
                    "message": "Candidate rejected",
                    "source_key": source_key,
                    "title": candidate.title,
                    "reason": result.reason,
                }
            )
        return {
            "source_key": source_key,
            "source_type": source_type,
            "status": "success",
            "items_found": len(candidates),
            "items_valid": len(valid),
            "items_invalid": invalid,
            "items": valid,
            "logs": logs,
        }

    try:
        result = asyncio.run(run())
    except Exception as exc:
        result = {
            "source_key": source_key,
            "source_type": source_type,
            "status": "failed",
            "items_found": 0,
            "items_valid": 0,
            "items_invalid": 0,
            "items": [],
            "error_message": str(exc),
            "logs": [{"level": "error", "message": str(exc)}],
        }
        if source_run_id:
            _complete_source_run(source_run_id, {**result, "task_id": task_id})
        raise
    if source_run_id:
        _complete_source_run(source_run_id, {**result, "task_id": task_id})
    return result
