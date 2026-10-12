# Auditor automático de fuentes (issue #57) — feature ODD

## Objective
Sistema de auditoría reproducible para todas las fuentes: 8 dimensiones, estados operativa/degradada/fallida/pendiente, exportación XLSX/CSV/JSON/Markdown y modo probe opt-in. Fases 0-1 primero; fase 2 simulada si tests en verde.

## Problem
Ver issue #57 y `docs/plans/opencode-auditoria-203-fuentes.md` (rama `plan/opencode-auditoria-203-20261012`, 11.6KB): sin auditoría sistemática no hay forma de saber qué fuente está sana; ASCUN evidenció truncamientos, cuarentena capada y noticias como grants.

## Why
Pedido explícito del usuario con plan detallado + issue #57. Todo en worktree aislado, sin tocar producción.

## Scope
- IN: fases 0 (contrato) y 1 (history read-only + CLI + exports + tests) en worktree `$HOME/convocaradar-worktrees/auditor-fuentes-203-20261012` (rama `auditor-fuentes-203-20261012`); fase 2 simulada solo si fase 1 verde.
- OUT: probe real con red, migraciones productivas, push/merge/deploy, sudo, timers, tocar `/srv`, PR #55/#56.
- Desviación documentada: el plan pide base en HEAD productivo `70a6409`, objeto inexistente localmente (solo existe en el servidor); se trabaja desde `origin/main` (`2a9f711`) y el auditor no depende de deltas prod.

## Constraints
- TDD; history estrictamente read-only sin requests externos; `UNKNOWN` antes que `PASS` inventado; nada hardcodeado (inventario completo incl. deshabilitadas).
- Commits locales Conventional en la rama del worktree, sin push (lo decide el usuario).

## Tasks
- [x] **A0 (P0 writer)** ✅ 2026-10-12 Contrato tipado con PASS/FAIL/UNKNOWN + evidencia obligatoria.
- [x] **A1 (P0 writer)** ✅ 2026-10-12 Módulo history + CLI + 8 dimensiones + 4 exports + 21 tests verdes (spot-check padre OK, diff-check limpio). Commit local `6cd88a8`, sin push (regla del issue).
- [x] **A2 (P1 writer)** ✅ 2026-10-12 Fase 2 simulada (3 conectores, dry-run, pilotos reales bloqueados sin consentimiento).
- **Cierre**: objetivo cumplido — sistema de auditoría entregado, NO certificación de fuentes. Rama pusheada `auditor-fuentes-203-20261012` (sin merge a main). Pendientes: probe real con budgets + piloto ASCUN (el worker frenó bien: no existe probe real con resguardos, hacerlo sería red ad-hoc), dashboard 203, fase 3 runbook ✅ + regresión ✅.

## Acceptance
- Criterios 1-10 del plan (tests verdes sin side-effects, todas las filas, PASS/FAIL/UNKNOWN con evidencia, 4 formatos, prioridades P0-P3, skips visibles, probe simulado, `git diff --check` limpio, sin declarar 203 sanas).
- Commits locales, informe final con archivos y pendientes.

## Progress
- 2026-10-12: doc creado; worktree listo en `origin/main` (desviación 70a6409 documentada). Mirror Engram pendiente.

## Next step
- Delegar A0+A1 al writer en worktree.
