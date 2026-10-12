"""Tests de exports, CLI y probe simulado. Sin DB ni red."""

from __future__ import annotations

import csv
import json

import pytest

from app.audit.cli import main
from app.audit.exports import write_csv, write_json, write_markdown, write_xlsx
from app.audit.history import audit_all
from app.audit.loaders import load_snapshot
from app.audit.probe import SIMULATED_CONNECTORS, run_simulated_probe
from tests.test_source_audit import _opp, _run, _src


def _results():
    sources = [_src(id="s1", key="sana"), _src(id="s2", key="rota", enabled=False)]
    runs = {"s1": [_run(status="success", age_h=h) for h in (1, 2, 3)], "s2": []}
    opps = {"s1": [_opp(id=f"o{i}", external_id=f"e{i}", title=f"Beca {i} {i}",
                         official_url=f"https://example.com/c/{i}") for i in range(3)],
            "s2": []}
    return audit_all(sources, runs, opps)


def test_exports_csv_json_xlsx_markdown(tmp_path):
    results = _results()
    write_csv(results, tmp_path / "a.csv")
    write_json(results, tmp_path / "a.json")
    write_xlsx(results, tmp_path / "a.xlsx")
    write_markdown(results, tmp_path / "r.md")
    rows = list(csv.DictReader((tmp_path / "a.csv").open(encoding="utf-8")))
    assert len(rows) == 2  # inventario completo incl. deshabilitada
    assert {r["source_key"] for r in rows} == {"sana", "rota"}
    data = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert len(data) == 2 and all("checks" in d and len(d["checks"]) == 8 for d in data)
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "rota" in md and "Inventario completo" in md


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def test_cli_history_with_snapshot(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(_dump({
        "sources": [_src(id="s1", key="demo")],
        "runs": {"s1": [_run()]},
        "opportunities": {"s1": [_opp()]},
    }), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--mode", "history", "--output", str(out),
                 "--input", str(snap)]) == 0
    for f in ("auditoria.csv", "auditoria.json", "auditoria.xlsx", "resumen.md"):
        assert (out / f).exists(), f


def test_cli_history_filters(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(_dump({
        "sources": [_src(id="s1", key="a"), _src(id="s2", key="b")],
        "runs": [{"source_id": "s1", **{k: v for k, v in _run().items() if k != "id"}}],
        "opportunities": [],
    }), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--mode", "history", "--output", str(out), "--input", str(snap),
                 "--source-key", "a", "--limit", "5"]) == 0
    rows = list(csv.DictReader((out / "auditoria.csv").open(encoding="utf-8")))
    assert [r["source_key"] for r in rows] == ["a"]


def test_load_snapshot_flat_and_nested(tmp_path):
    snap = tmp_path / "s.json"
    snap.write_text(_dump({
        "sources": [_src(id="s1", key="x")],
        "runs": [{"source_id": "s1", "status": "success"}],
        "opportunities": {"s1": [_opp()]},
    }), encoding="utf-8")
    sources, runs_by, opps_by = load_snapshot(snap)
    assert len(sources) == 1 and len(runs_by["s1"]) == 1 and len(opps_by["s1"]) == 1


def test_probe_simulado_tres_conectores_sin_red():
    assert len(SIMULATED_CONNECTORS) >= 3
    probes = run_simulated_probe()
    assert all(p.latency_ms >= 0 for p in probes)
    assert any(not p.reachable and p.status_code is None for p in probes)  # timeout != 404


def test_probe_rechaza_piloto_no_simulado():
    with pytest.raises(ValueError, match="consentimiento"):
        run_simulated_probe(["fuente-real-no-simulada"])


def test_cli_probe_dry_run_and_run(tmp_path, capsys):
    out = tmp_path / "p"
    assert main(["--mode", "probe", "--output", str(out), "--dry-run"]) == 0
    assert "0 red real" in capsys.readouterr().out
    assert main(["--mode", "probe", "--output", str(out)]) == 0
    assert (out / "probe-simulado.txt").exists()
