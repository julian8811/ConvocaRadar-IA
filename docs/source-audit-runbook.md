# Runbook — Auditor de fuentes (Fase 3)

Sistema de auditoría de fuentes: clasifica cada fuente como `operativa`,
`degradada`, `fallida` o `pendiente` con evidencia por criterio.
Entregable: CLI + informes. Sin deploy, sin migraciones, sin dashboard
(el dashboard de 203 fuentes es posterior).

## 1. Comandos

Todos se ejecutan desde `apps/api` con `PYTHONPATH` apuntando al paquete
(o `python -m` con el venv del proyecto). Nada escribe en DB productiva.

### Modo history (default, solo lectura, sin Internet)

```bash
cd apps/api

# Snapshot sanitizado (recomendado: reproducible, sin DB)
PYTHONPATH=. python -m app.audit.cli --mode history \
  --input /ruta/snapshot.json --output /tmp/opencode/auditoria

# Una fuente
PYTHONPATH=. python -m app.audit.cli --mode history \
  --input /ruta/snapshot.json --output /tmp/opencode/a1 \
  --source-key ascun-convocatorias

# DB en modo lectura (solo SELECTs; nunca flush/commit).
# Requiere DATABASE_URL de LECTURA y aprobacion del operador.
PYTHONPATH=. python -m app.audit.cli --mode history \
  --output /tmp/opencode/a2 --limit 5
```

Formato del snapshot: `{"sources": [...], "runs": [...], "opportunities": [...]}`.
Acepta `runs`/`opportunities` anidados por fuente (`{sid: [...]}`) o planos
con `source_id`. Ver `app/audit/loaders.py:load_snapshot`.

Salida en `<output>/`: `auditoria.csv`, `auditoria.json`, `auditoria.xlsx`,
`resumen.md` (inventario, P0–P3, por fuente y por conector, cobertura).

### Modo probe (opt-in explícito, Fase 2 simulada)

```bash
# SIEMPRE primero el dry-run: 0 red real, describe el plan
PYTHONPATH=. python -m app.audit.cli --mode probe --dry-run \
  --output /tmp/opencode/probe --source-key ascun-convocatorias

# Probe simulado (fixtures en memoria; sigue sin tocar red)
PYTHONPATH=. python -m app.audit.cli --mode probe \
  --output /tmp/opencode/probe --source-key ascun-convocatorias
```

Conectores simulados hoy: `ascun-convocatorias`, `novo-nordisk-grants`,
`generic-rss-sample`. Cualquier otra clave falla con error explícito:
el piloto real requiere implementación con budgets + consentimiento
(ver §6, hoy NO implementado a propósito).

### Tests

```bash
cd apps/api
python -m pytest tests/test_source_audit.py \
  tests/test_source_audit_exports.py \
  tests/test_source_audit_connectors.py -q
```

## 2. Interpretación de estados y dimensiones

Veredicto global (`app/audit/history.py:_verdict`):

| Veredicto    | Significado                                                     |
|--------------|-----------------------------------------------------------------|
| `operativa`  | Dimensiones críticas verificadas (extracción, persistencia, estabilidad en PASS). `UNKNOWN` no crítico queda como limitación informativa. |
| `degradada`  | Fallos no críticos (enlaces, fechas, pertinencia, duplicados). P1 si >1 fallo, P2 si 1. |
| `fallida`    | Fallo en dimensión crítica o fuente auto-pausada. P0 si auto-pausada o tasa de fallos ≥50 %. |
| `pendiente`  | Información insuficiente, fuente deshabilitada o sin ejecuciones. P3. |

Ocho dimensiones, cada una `PASS` / `FAIL` / `UNKNOWN` con evidencia
obligatoria. **Sin datos nunca es `PASS`.** `UNKNOWN` nunca se convierte
en `PASS`:

1. **conectividad** — histórico no prueba disponibilidad actual: nunca da
   `PASS` sin probe directo (`not_checked`). `FAIL` solo con errores de
   red observados o todos los runs fallidos.
2. **extracción** — vacíos recurrentes (≥3) = `FAIL`; un único run vacío
   puede ser cero legítimo (`UNKNOWN`, no `FAIL`).
3. **pertinencia** — heurística de ruido (noticias/empleo/editorial ≥40 %).
   Marca para revisión humana, nunca borra.
4. **enlaces** — URLs ausentes/inválidas ≥20 % = `FAIL`. Timeout ≠ 404:
   sin medición directa queda `UNKNOWN`, no "URL muerta".
5. **fechas** — `open` con cierre vencido o ≥80 % sin `close_date` = `FAIL`.
   Nunca inventar fechas.
6. **duplicados** — candidatos por `external_id`/URL normalizada/
   título+entidad+fecha. Solo reporta con muestras, nunca fusiona.
7. **persistencia** — captura `items_skipped` (`count_cap` vs `time_budget`)
   y cuarentena censurada: 100 registros es el tope, **no el total real**.
8. **estabilidad** — ventana de 10 runs, tasa de fallos, `auto_paused`.
   Un puntual no marca `fallida`.

Campos del resultado: `source_id`, `source_key`, `enabled`, `source_type`,
`verdict`, `severity` (P0–P3), `confidence` (baja con cada `UNKNOWN`/`FAIL`),
`reasons` ordenadas, `needs_human_review`, `evaluated_at`, `git_version`,
`limitations`, `counters`. `data_state` distingue `blocked_by_source`,
`not_applicable` y `not_checked`.

## 3. Limitaciones conocidas

- `history` no mide red: `conectividad` siempre `UNKNOWN` sin probe.
- Cuarentena topada a 100 (`QUARANTINE_CAP_PER_RUN`): el total real es
  desconocido; el informe lo marca como censurado.
- `PERSIST_MAX_ITEMS_PER_RUN=50`: `items_skipped` con `reason`
  `count_cap` (límite de cantidad) o `time_budget` (límite de tiempo).
- Heurísticas de pertinencia/ruido son aproximadas: todo `FAIL` de
  pertinencia exige revisión humana antes de actuar.
- El número de fuentes no está hardcodeado: toda fuente del inventario
  (incluidas deshabilitadas) genera una fila.

## 4. Costos y tiempos

- `history`: 0 requests externos, 0 costo. Solo CPU local + lectura.
  Ventana DB acotada: últimos 10 runs y 500 oportunidades por fuente.
- `probe --dry-run`: 0 requests. Siempre gratis y obligatorio antes de
  cualquier piloto.
- `probe` simulado actual: 0 requests reales.
- Piloto real (pendiente de implementar, §6): presupuesto por fuente de
  bajo riesgo ≈ 1–3 requests (1 listado + hasta 2 detalle), timeout total
  ≤60 s, concurrencia global ≤2 (≤1 por host), jitter entre llamadas,
  respeto de `429`+`Retry-After` y robots. STOP ante 429/WAF sin
  reintentos agresivos.

## 5. Rollback — cómo revertir una corrida

El auditor **no muta nada** por diseño (ver §7), así que el rollback es
trivial:

1. `history`/`probe` solo escriben archivos en `--output`. Revertir =
   borrar el directorio de salida. No hay nada que deshacer en DB,
   fuentes, oportunidades ni cron.
2. Si `--mode history` se usó contra DB (solo SELECTs), no hay estado
   que revertir: no existe `flush`/`commit` en `app/audit/`.
3. Si un piloto real futuro llegara a ejecutarse por error fuera de
   presupuesto: detener el proceso (Ctrl-C), conservar la salida para
   el informe, y reportar (no hay escrituras que compensar porque el
   probe tiene prohibido crear/actualizar oportunidades, emitir emails
   o encolar jobs).
4. Cambios de código del auditor: rama aislada, commits locales sin
   push; revertir = `git revert <sha>` o descartar la rama.

## 6. Pilotos por lotes (5 / 20 / resto) con revisión humana

Precondición: implementar el probe real opt-in con budgets (§4),
bloqueo SSRF/red interna, y `pending_manual_review` ante ambigüedad.
Hoy el probe real **no existe** (solo simulado): ningún piloto real
puede ejecutarse desde este código. Cuando exista:

- **Lote 0 — piloto (1 fuente):** `ascun-convocatorias`.
  `--dry-run` primero; ejecutar solo si ≤10 requests totales y respeta
  concurrencia/timeout/jitter/robots. Evidencia sanitizada al informe.
- **Lote 1 — 5 fuentes:** las de mayor impacto + 1 de cada tipo de
  conector genérico. Revisión humana del 100 % de `degradada`/`fallida`
  y de todo `needs_human_review=true` antes del siguiente lote.
- **Lote 2 — 20 fuentes:** resto de alto impacto. Revisión humana de
  P0/P1 y muestra del 25 % de P2/P3.
- **Resto:** en tandas de ≤20, solo tras validar el lote anterior.
  Criterio de avance: 0 incidentes (429/WAF/quejas) y <10 % de
  veredictos revertidos por revisión humana.
- **STOP inmediato** ante 429, WAF/captcha, o dry-run que exceda el
  presupuesto: se reporta, no se reintenta.

## 7. Garantías de no-mutación (verificables)

- `app/audit/probe.py`: sin sockets/DNS/HTTP (solo fixtures).
- `app/audit/history.py`, `exports.py`, `types.py`: funciones puras.
- `app/audit/loaders.py:load_readonly_db`: solo `SELECT`; sin
  `flush`/`commit`/`add`/`delete` en todo `app/audit/`.
- El probe tiene prohibido usar `run_source_inline`, persistir
  oportunidades, emitir emails, encolar jobs y llamar embeddings.
- Tests `test_source_audit_connectors.py`: `fetch` blindado (falla si se
  toca red) y congelamiento `deepcopy` de entradas para probar que el
  auditor clasifica sin mutar.
