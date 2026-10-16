# Remediación post-certificación (203 probadas) — feature ODD

## Objective
Convertir el mapa 157/8/16/7/15 en fixes: política de redirects legítimos, forense de los 16×404 (seed vs muerte real), documentar WAF, re-probar transitorios.

## Problem (evidencia 2026-10-12, `live-probe-real.json` por fuente)
- **15 `blocked_by_policy`**: redirects a hosts del mismo dueño (secihti.mx, uniandes.edu.co, mozilla, innpulsa, drive.google, betowa.sena, cdn.gob.pe, nzscholarships...) bloqueados por allowlist estricta. Mayoría legítimos → fix de política con validación, no bypass.
- **16 `live_dead` (todos 404 en el GET del probe)**: sospechoso — incluye `universidad-nacional-colombia` que rinde 37 ítems en producción. Forense por fuente: URL semilla desactualizada (fix seed) vs muerte real (cuarentena). 404 del probe ≠ muerte sin verificar.
- **7 `live_blocked` (WAF 403)**: anid, fondecyt, bogotá, devaid, sloan, eurimages, IAF. Sin fix externo; documentar + cuarentena con motivo.
- **8 transient + 2 SSL**: re-probe único; SSL = cert del sitio (documentar).

## Why
Cierre del ciclo auditoría→remediación; el mapa sin fixes no sirve.

## Scope
- IN: R-A fix política redirects + re-probe 15 (lote1 worktree); R-B forense 16×404 + fixes seed/cuarentena (main); R-C documentar 7 WAF; R-D re-probe 8+2.
- OUT: reescribir conectores sanos; fixes infinitos en muertos verificados; merge/deploy (separado).
- TDD en código; forense read-only con cortesía (1 GET secuencial, UA repo).

## Constraints
- Commits Conventional; ramas existentes (lote1 para probe, main para seeds); push sí, merge/deploy con autorización.
- 404 del probe nunca es veredicto final sin forense.

## Tasks
- [x] **R-A (P1 writer)** ✅ Política mismo-dueño + re-probe 15 (8 plenos + 4 parciales) + ajustes (pares gob.pe/NZ, evidencia over_budget, decisión Drive). Pusheado. Pendiente manual: uniandes TLS+WAF.
- [ ] **R-B (P1)** Forense 16×404 + fixes seed o cuarentena. Ruta: delegada (main). ✅ 8 re-mapeadas deployadas y verificadas (cherry `bdfa07c`, todas rinden, 0 failed); 6 pendientes de descubrimiento; unal intacta.
- [ ] **R-C (P1)** Documentar 7 WAF en fuentes-todas-on/cuarentenas.
- [ ] **R-D (P1)** Re-probe 8 transient + 2 SSL, documentar.

## Acceptance
- 15 redirects: política que distingue dueño legítimo vs externo, re-probe con veredicto.
- 16×404: cada una con fix seed o motivo de muerte verificable.
- Suite verde; sin regresiones.

## Progress
- 2026-10-12: doc creado con clases desde evidencia. Mirror Engram pendiente.

## Next step
- Delegar R-A + R-B en paralelo.
