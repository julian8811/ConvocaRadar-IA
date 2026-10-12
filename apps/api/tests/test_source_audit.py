"""Tests del auditor historico de fuentes (Fase 1) — TDD RED.

Casos exigidos por el plan: count_cap (50), cuarentena censurada (100),
expirados open, URL NULL, duplicados, cero legitimo, deshabilitadas,
run exitoso sin oportunidades, varios ultimos runs. Sin DB ni red.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit.history import audit_source
from app.audit.types import CheckStatus, Verdict

NOW = datetime.now(UTC).replace(tzinfo=None)


def _src(**kw):
    base = {
        "id": "s1",
        "key": "test-source",
        "name": "Test Source",
        "enabled": True,
        "source_type": "html",
        "base_url": "https://example.com/convocatorias",
        "auto_paused": False,
        "consecutive_empty_runs": 0,
    }
    base.update(kw)
    return base


def _run(status="success", age_h=1, **kw):
    ts = NOW - timedelta(hours=age_h)
    base = {
        "id": f"r-{age_h}-{status}",
        "status": status,
        "started_at": ts,
        "finished_at": ts,
        "items_found": 5,
        "items_created": 5,
        "items_updated": 0,
        "items_failed": 0,
        "error_message": None,
        "logs": [],
    }
    base.update(kw)
    return base


def _opp(**kw):
    base = {
        "id": "o1",
        "source_id": "s1",
        "external_id": "ext-1",
        "title": "Convocatoria de investigacion 2026",
        "entity": "Entidad X",
        "status": "open",
        "official_url": "https://example.com/conv/1",
        "close_date": (NOW + timedelta(days=30)).isoformat(),
    }
    base.update(kw)
    return base


def test_count_cap_marks_persistencia_fail_with_skipped():
    run = _run(logs=[{"level": "info", "message": "persist capped",
                       "reason": "count_cap", "items_skipped": 138}])
    res = audit_source(_src(), [run], [_opp()])
    check = res.checks["persistencia"]
    assert check.status == CheckStatus.FAIL
    assert check.evidence.counters.get("items_skipped") == 138
    assert check.evidence.counters.get("cap_reason") == "count_cap"
    assert res.verdict in (Verdict.DEGRADADA, Verdict.FALLIDA)


def test_quarantine_100_is_censored_not_total():
    logs = [{"level": "quarantine", "reason": "ruido", "title": f"n{i}"} for i in range(100)]
    run = _run(logs=logs)
    res = audit_source(_src(), [run], [_opp()])
    check = res.checks["persistencia"]
    assert check.status == CheckStatus.FAIL
    assert check.evidence.counters.get("quarantine_entries") == 100
    assert check.evidence.counters.get("quarantine_censored") is True
    assert any("100" in e for e in check.evidence.examples)


def test_expired_open_opportunities_fail_fechas():
    opp = _opp(status="open", close_date=(NOW - timedelta(days=5)).isoformat())
    res = audit_source(_src(), [_run()], [opp])
    check = res.checks["fechas"]
    assert check.status == CheckStatus.FAIL
    assert check.evidence.counters.get("expired_open") == 1


def test_null_urls_fail_enlaces():
    opps = [_opp(official_url=None), _opp(official_url=""),
            _opp(official_url="https://example.com/conv/3")]
    res = audit_source(_src(), [_run()], opps)
    check = res.checks["enlaces"]
    assert check.status == CheckStatus.FAIL
    assert check.evidence.counters.get("missing_url") == 2


def test_duplicates_reported_without_merging():
    opps = [_opp(id="o1", external_id="dup", title="Beca X"),
            _opp(id="o2", external_id="dup", title="Beca X"),
            _opp(id="o3", external_id="other", title="Beca Y",
                 official_url="https://example.com/conv/1")]
    res = audit_source(_src(), [_run()], opps)
    check = res.checks["duplicados"]
    assert check.status == CheckStatus.FAIL
    assert check.evidence.counters.get("duplicate_candidates", 0) >= 1
    assert len(opps) == 3  # sin fusionar registros


def test_single_empty_run_is_legitimate_zero_not_failed():
    run = _run(status="success", items_found=0, items_created=0)
    res = audit_source(_src(consecutive_empty_runs=1), [run], [])
    assert res.checks["extraccion"].status != CheckStatus.FAIL
    assert res.verdict != Verdict.FALLIDA


def test_recurrent_empty_runs_fail_extraccion():
    runs = [_run(status="success", age_h=h, items_found=0, items_created=0)
            for h in range(1, 7)]
    res = audit_source(_src(consecutive_empty_runs=6), runs, [])
    assert res.checks["extraccion"].status == CheckStatus.FAIL


def test_disabled_source_in_inventario_as_pendiente():
    res = audit_source(_src(enabled=False), [], [])
    assert res.enabled is False
    assert res.verdict == Verdict.PENDIENTE
    assert res.needs_human_review is True


def test_no_data_never_pass():
    res = audit_source(_src(), [], [])
    for check in res.checks.values():
        assert check.status != CheckStatus.PASS
    assert res.verdict == Verdict.PENDIENTE


def test_history_never_passes_conectividad_without_direct_measurement():
    runs = [_run(status="success") for _ in range(3)]
    res = audit_source(_src(), runs, [_opp()])
    assert res.checks["conectividad"].status != CheckStatus.PASS


def test_network_errors_fail_conectividad():
    run = _run(status="failed", items_found=0,
               error_message="Connection timeout after 30s")
    res = audit_source(_src(), [run, _run()], [_opp()])
    assert res.checks["conectividad"].status == CheckStatus.FAIL


def test_auto_paused_is_fallida_p0():
    res = audit_source(_src(auto_paused=True), [_run(status="failed")], [])
    assert res.verdict == Verdict.FALLIDA
    assert res.severity == "P0"


def test_all_failed_runs_is_fallida():
    runs = [_run(status="failed", age_h=h, items_found=0,
                 error_message="boom") for h in range(1, 4)]
    res = audit_source(_src(), runs, [])
    assert res.verdict == Verdict.FALLIDA


def test_healthy_source_is_operativa():
    runs = [_run(status="success", age_h=h) for h in range(1, 4)]
    opps = [_opp(id=f"o{i}", external_id=f"e{i}", title=f"Convocatoria {i} tema {i}",
                 official_url=f"https://example.com/conv/{i}") for i in range(5)]
    res = audit_source(_src(), runs, opps)
    assert res.verdict == Verdict.OPERATIVA
