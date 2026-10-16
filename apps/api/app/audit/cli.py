"""CLI del auditor: `python -m app.audit.cli --mode history --output <dir>`.

Defaults: modo history, solo lectura, sin Internet. `--input <snapshot.json>`
para fixtures/JSON sanitizado; sin --input intenta DB read-only via
DATABASE_URL (SELECTs unicamente, sin flush/commit).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.audit.exports import write_csv, write_json, write_markdown, write_xlsx
from app.audit.history import audit_all
from app.audit.loaders import load_snapshot
from app.audit.probe import run_simulated_probe


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auditor historico de fuentes (solo lectura)")
    p.add_argument("--mode", choices=["history", "probe", "live-probe"],
                   default="history")
    p.add_argument("--output", required=True, help="directorio de reportes")
    p.add_argument("--input", default=None, help="snapshot JSON sanitizado")
    p.add_argument("--source-key", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="solo en probe: describe el plan sin tocar red (aqui: simulado)")
    p.add_argument("--allow-network", action="store_true",
                   help="solo en live-probe: autoriza red real con presupuestos "
                        "(exige tambien --source-key)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    if args.mode == "live-probe":
        # Aislamiento total del modo history: no toca DB ni snapshots.
        import asyncio
        import json as _json

        from app.audit.live_probe import build_dry_run_plan, run_live_probe
        from app.audit.live_probe import KNOWN_START_URLS, build_httpx_transport

        if not args.source_key:
            print("live-probe exige --source-key (opt-in por fuente)", file=sys.stderr)
            return 2
        urls = KNOWN_START_URLS.get(args.source_key, [])
        if args.dry_run or not args.allow_network:
            plan = build_dry_run_plan(args.source_key, urls or None)
            print(f"[dry-run] probe real {args.source_key}: "
                  f"{plan['estimated_requests']} requests estimadas, "
                  f"hosts={', '.join(plan['hosts']) or '?'}")
            print(f"[dry-run] riesgos: {'; '.join(plan['risks'][:3])}")
            if not args.allow_network:
                print("[dry-run] red NO autorizada: faltan --allow-network "
                      "(preflight, 0 red real). Piloto real requiere "
                      "autorizacion expresa posterior.")
            (out / "live-probe-plan.json").write_text(
                _json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0
        # Red real: UN solo GET (max_requests=1) via transporte instrumentado.
        # hosts autorizados = hosts de las start_urls conocidas de la fuente.
        from urllib.parse import urlparse as _urlparse
        authorized = sorted({(_urlparse(u).hostname or "").lower()
                             for u in urls} - {""})
        transport = build_httpx_transport()
        outcome = asyncio.run(run_live_probe(
            args.source_key, allow_network=True, start_urls=urls or None,
            transport=transport, authorized_hosts=authorized,
            max_requests=1))
        print(f"{outcome.source_key}: {outcome.status} "
              f"req={outcome.requests_made} evidencia en live-probe-plan.json")
        (out / "live-probe-plan.json").write_text(
            _json.dumps({"status": outcome.status,
                         "evidence": outcome.evidence},
                        ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        return 0 if outcome.status == "live_ok" else 1

    if args.mode == "probe":
        keys = [args.source_key] if args.source_key else None
        if args.limit is not None and keys is None:
            from app.audit.probe import SIMULATED_CONNECTORS
            keys = sorted(SIMULATED_CONNECTORS)[: args.limit]
        if args.dry_run:
            planned = keys or ["ascun-convocatorias", "novo-nordisk-grants",
                                "generic-rss-sample"]
            print(f"[dry-run] probes simulados (0 red real): {', '.join(planned)}")
            return 0
        probes = run_simulated_probe(keys)
        for pr in probes:
            print(f"{pr.source_key}: reachable={pr.reachable} "
                  f"status={pr.status_code} latency={pr.latency_ms}ms — {pr.note}")
        (out / "probe-simulado.txt").write_text(
            "\n".join(f"{pr.source_key}|{pr.reachable}|{pr.status_code}|"
                       f"{pr.latency_ms}|{pr.note}" for pr in probes),
            encoding="utf-8")
        return 0

    # ── history ──
    if args.input:
        sources, runs_by, opps_by = load_snapshot(args.input)
    else:
        from app.db.session import SessionLocal
        from app.audit.loaders import load_readonly_db

        with SessionLocal() as session:
            sources, runs_by, opps_by = load_readonly_db(
                session, limit=args.limit, source_key=args.source_key)
            results = audit_all(sources, runs_by, opps_by)
            if args.source_key:
                results = [r for r in results if r.source_key == args.source_key]
        write_csv(results, out / "auditoria.csv")
        write_json(results, out / "auditoria.json")
        write_xlsx(results, out / "auditoria.xlsx")
        write_markdown(results, out / "resumen.md")
        print(f"fuentes auditadas: {len(results)} -> {out}")
        return 0

    if args.source_key:
        sources = [s for s in sources if s.get("key") == args.source_key]
    if args.limit is not None:
        sources = sources[: args.limit]
    results = audit_all(sources, runs_by, opps_by)
    write_csv(results, out / "auditoria.csv")
    write_json(results, out / "auditoria.json")
    write_xlsx(results, out / "auditoria.xlsx")
    write_markdown(results, out / "resumen.md")
    print(f"fuentes auditadas: {len(results)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
