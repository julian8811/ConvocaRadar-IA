"""Probe active source contracts without mutating application data."""
from __future__ import annotations
import asyncio
import re
import sys
import httpx
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source

async def probe(source: Source, client: httpx.AsyncClient) -> tuple[str,str,str]:
    try:
        response = await client.get(source.base_url, follow_redirects=True)
        body = response.text[:2_000_000]
        if response.status_code >= 400:
            return source.key, "blocked", str(response.status_code)
        if len(body) < 300:
            return source.key, "empty", str(len(body))
        if source.source_type == "html" and not re.search(r"(convoc|call|grant|fund|opportun|beca|fellow|deadline|cierre)", body, re.I):
            return source.key, "contract-warning", "no opportunity markers"
        return source.key, "ok", f"{response.status_code}/{len(body)}"
    except Exception as exc:
        return source.key, "error", type(exc).__name__

async def main() -> int:
    with SessionLocal() as db:
        sources = list(db.scalars(select(Source).where(Source.key.in_({"bndes-brasil","finep-brasil","embrapii-brasil","caf-convocatorias","dane-convocatorias","icfes-convocatorias","ideam-convocatorias","minsalud-convocatorias","sebrae-brasil","senescyt-ecuador","uis-investigacion","uptc-investigacion","colombia-cientifica"}))))
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(headers={"User-Agent": "ConvocaRadarContractProbe/1.0"}, limits=limits, timeout=timeout) as client:
        results = await asyncio.gather(*(probe(source, client) for source in sources))
    counts: dict[str,int] = {}
    for key, status, detail in sorted(results):
        counts[status] = counts.get(status, 0) + 1
        print(f"{status:16} {key:40} {detail}")
    print("summary", counts)
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

