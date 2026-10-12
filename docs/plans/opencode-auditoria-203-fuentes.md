# Encargo OpenCode — Auditor automático integral de fuentes (ConvocaRadar-IA)

**Fecha de referencia:** 2026-10-12. **Prioridad:** robustez, evidencia y seguridad de producción.

## Objetivo
Construir en el repositorio un **auditor automatizado de las fuentes registradas** capaz de clasificar cada una como `operativa`, `degradada`, `fallida` o `pendiente`, con razones verificables y evidencia por criterio. Debe funcionar para todas las fuentes activas, no solo para ASCUN, sin introducir cambios en los datos productivos. Separar calidad técnica del conector, pertinencia editorial y vigencia de las oportunidades.

**Inventario previamente observado, NO asumir vigente:** 204 fuentes en total, 203 habilitadas. Verificar en modo lectura cuando esté permitido; no tratar una fuente como auditada por aparecer `enabled=true`.

## Contexto verificado
- Servidor universitario: `/srv/apps/convocaradar`. Rama/HEAD productivo al 12-oct: `server/observatorio-production-prebasepath-20260909` / `70a6409f4e431ffd0385867f5aa3a9805c25d7e1`.
- La rama `main` remota **diverge de producción**. Trabajar únicamente desde un `git worktree` basado en el HEAD productivo; no ejecutar `git pull`, `git reset`, `git merge`, `git rebase` o `docker compose up` sobre el checkout en servicio.
- Imagen actualmente desplegada: `convocaradar-api:ascun-632f3853aec6` para API y worker, aplicada mediante override `/home/ubuntu/convocaradar-deploy/ascun-new-20261012T154940Z.yml`. No reiniciar API/worker ni reemplazar imágenes.
- PR #55: validación URL ASCUN con streaming GET y preservación de URL existentes, ya portada a producción mediante cherry-pick. PR #56: corrección de conector especializado ASCUN, clasificación de noticias y búsqueda por títulos/paginación; **borrador, NO fusionada ni desplegada**. Mantenerla independiente de este encargo.
- Sistema existente `convocaradar-status-reconcile.timer` activo, no duplicar cron/timer.
- Tablas `sources`, `source_runs`, `opportunities`. `SourceRun.logs` tiene registros de cuarentena con máximo `QUARANTINE_CAP_PER_RUN=100`; el límite visible **no es el total real**.
- `apps/api/app/scraper/runner.py` limita `PERSIST_MAX_ITEMS_PER_RUN=50`. Una ejecución ASCUN tuvo 188 encontrados, 50 actualizados, 138 omitidos por `count_cap`.
- Ejemplo ASCUN: 67 fichas, 63 sin URL, 0 con `close_date`; `WordPressGrantsConnector` absorbía noticias como `grants/research/health`. No inferir relevancia por fuente `status=success`.

## Fases de implementación en una rama aislada (ejecutar en orden)

### Fase 0. Inspección y contrato de diseño
1. Inspeccionar modelos, contratos de conectores, esquema de fuentes/ejecuciones, servicios de validación, helpers de cuarentena, métricas, configuración, pruebas y panel web existentes. Partir del código **real del worktree**, no de suposiciones sobre `origin/main`.
2. Establecer un contrato de datos tipado para `SourceAuditResult`, `AuditCheckResult`, `AuditEvidence` con `source_id`, `source_key`, nombre, habilitada, tipo, estado, resultado de ocho dimensiones, severidad, confianza, ejemplos, errores, tiempos, contadores, fecha de evaluación, versión git, limitaciones y motivos para revisión humana.
3. Toda valoración debe tener `PASS`, `FAIL` o `UNKNOWN` y evidencia. Una dimensión sin datos nunca da `PASS`. Distinguir `blocked_by_source`, `not_applicable` y `not_checked` cuando corresponda. No declarar las 203 fuentes sanas sin ejecutar auditorías de calidad verificables.

### Fase 1. Auditoría HISTÓRICA sin solicitudes externas ni mutaciones
Implementar módulo reutilizable con CLI, tipos y pruebas. Analizar datos ya almacenados (`sources`, `source_runs`, `opportunities`) mediante sesiones SQL de **solo lectura** o snapshots de pruebas, sin tocar `last_run_at`, `last_success_at`, `consecutive_empty_runs`, `enabled`, `auto_paused`, `opportunities` ni tareas de cron.
Verificaciones por fuente, todas independientes y con evidencia:
1. **Conectividad**: últimos estados, errores y tiempos; histórico no verifica disponibilidad HTTP actual → `UNKNOWN` cuando no hay medición directa válida.
2. **Extracción**: cobertura de resultados y tendencia, éxitos vacíos recurrentes, errores, paginación y truncamientos; cero resultados puede ser legítimo.
3. **Pertinencia**: proporción razonable de noticias/empleo/editorial/no oportunas, ejemplos con URL y confianza; clasificadores heurísticos deben marcar revisión, no borrar.
4. **Enlaces**: cantidad de URLs ausentes/inválidas; distinguir URL no registrada, timeout, error HTTP definitivo, bloqueo 403/429, validación indeterminada; no equiparar timeout con 404.
5. **Fechas y vigencia**: % `close_date` desconocidos, expirados `open`, vigencia indeterminada; no inventar fechas ni etiquetar abierto sin pruebas.
6. **Duplicados**: IDs externos, URLs normalizadas y títulos/entidad/fecha; reportar candidatos con muestras, sin fusionar registros.
7. **Persistencia**: `items_found`, `created`, `updated`, `failed` y eventos `persist capped` con `items_skipped`; distinguir `count_cap` y `time_budget`; cuarentena truncada a 100 no es total.
8. **Estabilidad**: últimas N ejecuciones, tasa de fallos, variación, `auto_paused`, rendimientos y tendencias; no etiquetar fallida solo por una ejecución puntual.
Determinación global: `fallida` para fallo técnico grave observado, `degradada` si hay problemas serios de calidad/cobertura, `operativa` **solo si las dimensiones críticas están efectivamente verificadas**, `pendiente` si información insuficiente. Mostrar gravedad y razones ordenadas; no convertir `UNKNOWN` en `PASS`.
Generar **CSV, JSON y XLSX** reproducibles en un directorio de reportes bajo worktree o ruta configurable, más resumen Markdown: inventario, problemas priorizados P0/P1/P2/P3, por fuente y por conector, ejemplos, URLs/fechas, pruebas aplicadas/omitidas y cobertura de comprobaciones. Reportes versionados de código, no datos secretos. Separar ejecución de prueba de resultados productivos.
CLI preferida `python -m app.audit.cli --mode history --output <dir> [--source-key X] [--limit N]`, adaptar a arquitectura real. Defaults: **modo history, solo lectura**, sin Internet. Si no se puede conectar a la DB, soportar fixtures/JSON sanitizado.
Unit tests incluidas para 0 resultados legítimos, 100 cuarentenas censuradas, 50 persistencia cap, URLs NULL, expirados, fuentes inhabilitadas, run exitoso sin oportunidades y varios últimos runs.

### Fase 2. Pruebas de conector en memoria, lectura externa OPCIONAL
Diseñar `--mode probe` como **opt-in explícito**, nunca de forma implícita al importar clases. Debe:
- usar `connector_for` / `fetch` / `parse` / `validate` sobre fuentes seleccionadas, sin usar `run_source_inline`, sin crear ni actualizar oportunidades, sin emitir emails, sin jobs persistentes, sin embeddings de terceros y sin desplegar;
- aplicar timeouts totales, cancelación, tope de consultas y bytes por respuesta, limitación global de concurrencia (por defecto 2), **por host** <=1, pausas/jitter y budgets diarios por host; respetar `429`+`Retry-After` y robots/políticas de acceso; reportar los que no se deben sondear;
- bloquear SSRF, localhost/red interna, redirects a hosts no autorizados, rutas privadas, usuarios/contraseñas y secretos, y prohibir escaneos masivos;
- opción `--dry-run` describe el plan/red antes de tocar la red, mostrando número estimado de solicitudes y riesgos.
- cache de disponibilidad con `positive` y `negative transient` diferenciados. Timeout/network/403/429 no es URL muerta; nunca cachear un timeout como 404 durante 24 horas.
- muestras acotadas de URL y candidatos con decisiones editoriales explicables y sin datos personales.
- clasificación en `pending_manual_review` ante ambigüedad o datos de postulación inconsistentes, en vez de inventar certidumbre.
- permitir `--source-key ascun-convocatorias`, `--source-key novo-nordisk-grants` y otra muestra genérica de bajo riesgo, con pruebas aisladas primero; ampliar por lotes **solo tras validar piloto**.

### Fase 3. Integración/control de calidad sin deploy
Incluir pruebas de regresión de conectores (no duplicar ni alterar PR #56), contratos y errores de clasificación. Producir documento `docs/source-audit-runbook.md`: comandos history/probe, interpretación de estados, campos y limitaciones, costos, métricas y rollback. Si se necesitan migraciones SQL/API/UI, **presentar diseño y pruebas en rama**, no ejecutar migraciones en producción.
Solo tras evaluar pilotos, proponer ejecución escalonada por lotes (p. ej., 5/20/resto), prioridad por impacto, y revisión humana de casos ambiguos. Dashboard de 203 fuentes puede ser posterior; preferir entregar CLI+informe robustos y testeados antes de frontend.

## Requisitos de seguridad de la sesión OpenCode
- NO `sudo` dentro del agente; NO `git push`, PR merge, deploy ni `docker compose up/down/restart`; NO `alembic upgrade`; NO escribir en DB de producción, `.env`, secretos, directorio `/srv/apps/convocaradar` o volúmenes Docker; NO instalar timers/cron ni purgar oportunidades.
- Al trabajar con tests no montar `/app/app` desde worktree en contenedor con UID diferente: los directorios de worktree pueden estar en modo `0700`. En pruebas previas funcionó montar solo archivos en modo `:ro`, `--user $(id -u):$(id -g)`, `-e PYTHONPATH=/app`, `--workdir /app`.
- No copiar secrets a logs/artefactos ni incluir direcciones/credenciales internas. Inspección de código sí; lecturas de DB de producción únicamente mediante herramienta de lectura con aprobaciones del operador, o mock.
- Preservar cambios existentes de otros worktrees, no mezclar ramas PR #55/#56. Tener en cuenta que `main` remoto y producción no tienen idénticos commits.
- Si OpenCode propone comandos destructivos, omitirse y pedir aprobación explícita antes de continuar.

## Criterios de aceptación demostrables
1. Tests automáticos del auditor en verde, con reporte de comandos/contadores, y sin side-effects de BD o red en `history`.
2. Cada fuente del inventario tiene una fila **incluidas inhabilitadas**, con `enabled` y justificación; número de fuentes no hardcodeado.
3. Ocho dimensiones por fuente, estado `PASS/FAIL/UNKNOWN`, evidencia, fecha e interpretación; métricas de pendientes explícitas.
4. CSV + JSON + XLSX + resumen Markdown generados sin secretos y validados en pruebas.
5. Prioridad técnica reproducible que distinga `fallida`, `degradada`, `pendiente`, `operativa` y `no se comprobó`.
6. Captura explícita de `items_skipped` y cuarentena censurada, `open` con cierre vencido, URLs ausentes y noticias falsas.
7. Probe opt-in protegido y reproducible con al menos tres conectores simulados, y pilotos reales solo con consentimiento; no crear más cargas a las fuentes.
8. `git diff --check` limpio, pruebas ejecutadas, `git status --short`, resumen de archivos, commit(s) local(es) sin push y pasos de revisión propuestos.
9. Prohibido declarar "203 fuentes corregidas" hasta medir y resolver cada problema; el entregable inicial es **el sistema de auditoría**, no la certificación de las 203.
10. Conservar todas las evidencias sin PII/secretos en reportes locales; no publicarlas automáticamente.

## Instrucción de ejecución a OpenCode
**Desarrollar primero Fase 0 y Fase 1 en el worktree**, con tests unitarios, CLI y documentación. Si se completa de forma sólida, continuar con la implementación segura de Fase 2 simulada, sin activar las consultas reales. Publicar la salida final con resultados y bloqueos, no prometer pruebas no ejecutadas. Todo cambio queda sin desplegar.
