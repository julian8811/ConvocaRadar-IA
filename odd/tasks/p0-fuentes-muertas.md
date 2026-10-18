# P0 fuentes muertas — migración + discovery (2026-10-16)

Migración de las 10 URLs canónicas a DB + discovery forense de 4 pendientes. sgc y unal quedan fuera (decisión explícita del usuario pendiente).
TDD: test-first con pytest (`apps/api/tests/`), por convención del repo (tests del auditor en verde).

## Specs
- S1 (verbatim usuario): "P0 primero: las 16 muertas"
- S2 (verbatim usuario): "Reviso URL por URL y te propongo nueva URL o baja para cada una"
- S3 (verbatim usuario): "si, generala" — autoriza migración de las 10 canónicas + discovery de las 4 con sitio vivo (flacso, rutann, cali, medellín). sgc y unal NO se tocan.
- S4: las 10 canónicas son las pineadas en `apps/api/tests/test_seed_canonical_urls.py` (CANONICAL_SEEDS) y ya presentes en `apps/api/app/db/seed.py`; la migración debe llevar esos mismos `base_url` + `allowed_domains` a las filas existentes en DB (el seed solo rige instalaciones nuevas).
- S5: discovery forense = ≤2 GETs por fuente, repo User-Agent, sin persistencia, sin reintentos ante 403/429; pinear canónica SOLO si aparece verbatim en el home HTML vivo de la propia fuente; si no, PENDING (nunca inventar URLs).
- S6: migración reversible (upgrade/downgrade) con test que la cubra; `git diff --check` limpio; sin push/merge (lo decide el usuario).

## Tasks
- [x] **T1 (P0 explore, S3/S5)** ✅ 2026-10-16 Discovery forense flacso/rutann/cali/camara-medellín → 4/4 PENDING-discovery (homes vivos 200, cero ocurrencias verbatim de convocatorias; nada inventado). Pasan a propuesta de baja o discovery manual.
- [x] **T2 (P0 writer, S3/S4/S6)** ✅ 2026-10-16 Migración alembic `0019_canonical_source_urls` + `test_0019_canonical_source_urls.py` (RED→GREEN observado) + chain test actualizado a head 0019. Sin commit/push.
- [x] **T3 (parent)** ✅ 2026-10-16 Verificación: 18 passed (migración+chain+seed) + 6/6 post-formato; `git diff --check` limpio; alcance = 2 archivos nuevos + ajuste chain test.

## Log
- L1 (verbatim usuario): "Realiza una auditoria"
- L2 (verbatim usuario): "Y qué hacemos para esto?"
- L3: auditoría entregó 157 live_ok / 16 dead / 15 policy / 7 blocked / 8 transient; 10/16 dead ya re-mapeadas en seed.py (probe testeó URLs viejas); sin sync seed→DB existente.
- L4 (verbatim usuario): "¿Te genero la migración de las 10 + el discovery de las 4?" → "si, generala"
