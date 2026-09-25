# Fortalecer ConvocaRadar (201 fuentes, en producción) — feature ODD

## Objective
Endurecer ConvocaRadar-IA como núcleo del centro de datos: operar sin ceguera,
calidad medible y costos IA controlados, sobre las 201 fuentes seed ya desplegadas
en el servidor universitario (`ecosistema.colmayor.edu.co/observatorio`).

## Problem
La app está desplegada (compose server endurecido, backup diario, runbooks) pero se
opera a ciegas: métricas en memoria, `/ops/health` casi vacío, sweep de 30 min sin
sharding para 201 fuentes, embeddings hash-local de baja señal, README desactualizado
(93 vs 201 reales). Verificado en código `main@7e92a83`.

## Why
Sin visibilidad del sweep y sin calidad medida no se puede escalar el ecosistema
del centro de datos (boletines, portal evidencias) ni sostener los KPIs
(≥30 convocatorias/mes, precisión ≥85%).

## Scope
- IN: repo ConvocaRadar-IA, ramas feature/*, compose server, docs del repo.
- OUT explícito: CEITTO (no pertenece al core), portal público nuevo (F4 posterior),
  GPU/vLLM/K8s (fase DGX documentada, no se instala), producción universitaria
  (solo lectura de evidencias; ningún cambio directo en prod).

## Constraints
- PC dev: i7-12700H, 35 GiB RAM, 777 GB libres, WSL2 **sin Docker** (integración
  Docker Desktop inactiva) → `docker compose` local bloqueado hasta habilitarlo;
  verificación vía pytest/ruff directos.
- Sin GPU CUDA → nada de vLLM; IA = APIs comerciales (Gemini + Codex) + Ollama CPU
  solo dev.
- Commits: Conventional Commits, sin atribución IA. Push/PR/merge los decide el usuario.
- TDD: ON por convención del repo (CI corre pytest en cada push, 100+ archivos de
  test). Runner API: `cd apps/api && pytest tests/`. Web: `npm run test` (vitest).
- Delivery: `ask-on-risk` (default). Presupuesto ~400 líneas autoradas por tarea
  (heurística, no cap).

## Tasks

- [x] **T1 (P0 docs)** Conciliar inventario 201 ✅ commit `cca6d1a`
      (README 93→201 + 10→16 migraciones; `seed.py:4235`, `dashboard.py:49`,
      `api.ts:270` 123→201; `entrega-universidad.md` overlay→`server.yml`,
      RAM 8 GB, nginx solo web:3001 con rewrites `/api/v1` verificados en
      `next.config.ts:25-34`). Checks: `grep -c '"key":'` = 201; sin refs stale
      fuera de este doc; `pytest -k "seed or source"` → 206 passed; ruff exit 0.
      Ruta: inline (fixes mecánicos).
- [x] **T2 (P0 ops)** Gauges en `/metrics` ✅ commit `1d9f304` (writer delegado;
      `compute_sweep_gauges`: due_queue_depth, sweep_lag_seconds, pending_alerts
      desde DB; `/metrics` degradado 503 con snapshot in-memory si cae la DB;
      `test_metrics_sweep.py` 9 tests). Checks: writer 81 passed + 9 passed + ruff 0;
      spot-check padre 81 passed. Nota: `/metrics` con DB caída pasa de 500 a 503
      (Prometheus lo ve como scrape fallido, `up==0` lo cubre). Ruta: delegada.
- [x] **T3 (P0 perf)** Concurrencia por tier + medición ✅ commit `7282950` (writer
      delegado; env `SCRAPING_MAX_CONCURRENCY_{STRATEGIC,COMPLEMENTARY,EXPERIMENTAL}`,
      defaults 3/2/1 = pool 6 actual, clamp al cap global; semáforo global + por tier,
      strategic-first; `sweep_duration_seconds` + `sweep_overrun` en `/metrics`).
      Sin migraciones; locks/pause/budgets/timeout intactos; reversible. Checks:
      writer 103 passed + ruff 0; spot-check padre 103 passed. Con `sweep_overrun`
      en prod se decide el sharding estructural con datos. Ruta: delegada.
- [ ] **T4 (P1 calidad)** Cuarentena visible en `/sources` + métricas por cohorte
      (≥30/mes, precisión ≥85%). Checks: tests dedup/scoring.
- [ ] **T5 (P1 ia)** Gateway IA comercial (Gemini + Codex, fallback local) con caché y
      cuotas por org; trazabilidad costo/latencia. Checks: tests `ai_*`.
- [ ] **T6 (P1 respaldo)** Copia off-site/S3 del backup + `verify` robusto si cron cae;
      restore ensayado con runbook. Checks: scripts en `apps/backup/`.
- [ ] **T7 (P2 seg)** `BOOTSTRAP_SOURCES_ON_STARTUP=false` en server + rotación de
      secretos documentada. Checks: `compose_and_env`, docs.

## Acceptance
- F1 (T1-T3): inventario único 201, `/metrics` con las 3 gauges, sweep sin overrun
  crónico medido.
- F2-F3 (T4-T7): cuarentena + métricas por cohorte, gateway con cuotas, restore
  probado, secretos rotables.

## Progress
- 2026-09-25: feature doc creado en `feature/convocaradar-fortalecer-201`. Ruta: mapa
  delegado (explore), doc inline. Supuesto ante pregunta sin respuesta (ops vs sweep):
  arranco por T1 (desbloquea todo, 0 riesgo).

## Verification evidence
- (se anexa por tarea: comando → resultado observado)

## Next step
- T1 docs conciliación 201.
