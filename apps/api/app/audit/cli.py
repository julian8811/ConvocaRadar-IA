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
    p.add_argument("--mode", choices=["history", "probe"], default="history")
    p.add_argument("--output", required=True, help="directorio de reportes")
    p.add_argument("--input", default=None, help="snapshot JSON sanitizado")
    p.add_argument("--source-key", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="solo en probe: describe el plan sin tocar red (aqui: simulado)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

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
