# Vigencia: purga vencidas + gate de cierre + sweeper — feature ODD

## Header
Objetivo: (1) purgar oportunidades no vigentes, (2) programar gate central que rechaza registros sin `close_date` futura, (3) sweeper diario que auto-purga vencidas con backup rotativo. Basal prod 2026-10-18: TOTAL=2986, closed=1265, past_close=1297, unknown=1471 (sin fecha, <180d), open=233, closing_soon=17.

## Specs
- S1 (verbatim usuario): "requiero purgar todas las oportunidades viejas en la plataforma que no estén vigentes, y que quede programado que no se registran convocatorias que no presenten vigencia, que no tengan estado abierto y que sean verificadas con fecha de cierre"
- S2 (scope purga aprobado): 1297 con `close_date` pasada, con backup + verify. Excluido: 1465 unknown sin fecha (no probado).
- S3 (gate aprobado): central al persistir (post-enrichment): sin `close_date` o vencida → se rechaza. El status deriva de fechas (open/closing_soon), sin doble gate.
- S4 (sweeper aprobado): diario, auto-purga vencidas con backup rotativo.
- S5: tests RED→GREEN por regla, `diff --check` limpio, sin push/merge (usuario decide). Migración solo si el gate necesita estado; si es código puro, sin migración.

## Tasks
- [x] **T1** ✅ 2026-10-18 Purga 1297 vencidas: IDs live (1297 exactos), backup 8.4MB server+local, dependents 1297+1297, DEL 1297, REMAIN past_close=0. GLOBAL: TOTAL=1689 close=224 open=233 fund=176 (fund cayó 312: las vencidas traían montos; plataforma ahora solo vigente).: backup con assert + dependents-first + delete + verify 0 past_close + re-medir.
- [x] **T2-código** ✅ 2026-10-18 Gate `vigencia_reject_reason` en runner post-validate + quarantine `sin_fecha` + stats. RED→GREEN (3 failed→4 passed); contratos actualizados (quarantine close por defecto, enrichment fixture a dic-2026). Hallazgo: el clasificador matchea `dead` dentro de `deadline` → razones sin esa palabra. Suites: 26 passed, diff limpio. Deploy 2026-10-18: guard IDLE, rebuild, healthy; verify vivo con novo+findeter single → `dom_unchanged_skip` (gate probado por 26 tests + wiring en chokepoint).
- [ ] **T3** Sweeper diario vencidas + backup rotativo + scheduling existente + tests + deploy + verify.
- [ ] **T4** Re-medir cobertura final, delta vs basal, cerrar.

## Log
- L1 (verbatim usuario): "requiero purgar todas las oportunidades viejas en la plataforma que no estén vigentes, y que quede programado que no se registran convocatorias que no presenten vigencia, que no tengan estado abierto y que sean verificadas con fecha de cierre"
- L2 2026-10-18: medición viva (closed=1265, past_close=1297, unknown=1471, open=233). Aprobado: purga 1297 / gate duro post-enrichment / sweeper diario. Exclusión explícita: unknown sin fecha no se purga.
