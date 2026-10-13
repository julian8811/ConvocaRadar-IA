# Fase 4 — probe real protegido (issue #58) — feature ODD

## Objective
Convertir el auditor en verificación real: precisión histórica corregida, certificación viva separada, probe real opt-in con budgets y tests de seguridad offline. Piloto ASCUN solo dry-run (ejecución con autorización expresa posterior, NO en este encargo).

## Problem
Issue #58: (1) `quarantine_censored` se marca por suma de runs en vez de tope individual; (2) `operativa` histórico se confunde con verificación en vivo; (3) `probe.py` es solo simulado; sin probe real con resguardos no hay certificación posible.

## Why
Encargo ordenado del usuario (5 pasos) + issue #58. Rama de trabajo separada desde el auditor.

## Scope
- IN (worktree, rama `fase4-probe-real-20261012` desde `auditor-fuentes-203-20261012`): fix cuarentena por-run + tests (60+40 no, 100 sí); `verification_scope`/`live_certified` + criterios certificación viva (sin retro-certificar); probe real opt-in (`--allow-network` + `--source-key` + `--dry-run` preflight, SSRF/privados bloqueados, budgets auditables, adapter instrumentado o `blocked_by_policy`, clasificación HTTP con TTLs); tests offline de todos los casos de seguridad; dry-run ASCUN con plan (cero red).
- OUT: piloto real (paso 4, requiere aprobación expresa posterior), escala 5/20/resto (paso 5), prod/.env/cron/deploy/merge/push, PR #55/#56.
- TDD; commits locales Conventional sin push.

## Constraints
- `history` sigue read-only sin red; `simulated` intacto; presupuestos sobre requests efectivas; `UNKNOWN` antes que certificar.
- Prohibiciones #57 permanentes.

## Tasks
- [x] **F1 (P1 writer)** ✅ 2026-10-12 Precisión: cuarentena por-run + `verification_scope`/`live_certified` + criterios viva (sin retro-certificar).
- [x] **F2 (P1 writer)** ✅ 2026-10-12 Probe real opt-in (`--allow-network` + `--source-key` + dry-run, SSRF, budgets, adapter/`blocked_by_policy`, TTLs).
- [x] **F3 (P1 writer)** ✅ 2026-10-12 27 tests seguridad offline. Spot-check padre: 54 passed + diff limpio. Rama pusheada `fase4-probe-real-20261012`.
- [x] **F4 (operador)** ✅ 2026-10-12 Piloto ASCUN ejecutado (2/10 requests, 200 OK, 20/20 URLs; pertinencia con caveat: mayormente noticias). Veredicto: CONTINUAR A 5 condicional (con muestra de títulos). Evidencia commiteada + pusheada.
- **Cierre 2026-10-12**: escalado completo **203/203** (157 live_ok, 8 transient, 16 dead, 7 blocked, 15 blocked_by_policy). Rama pusheada. Remediation fuente por fuente = trabajo futuro fuera de este encargo.

## Acceptance
- Criterios #58: history read-only, tests sin red, budgets efectivos, faltantes expresos, piloto NO ejecutado, `git diff --check` limpio, ramas/PRs separados.

## Progress
- 2026-10-12: doc creado; issue #58 leído. Mirror Engram pendiente.

## Next step
- Rama + delegar F1–F3.
