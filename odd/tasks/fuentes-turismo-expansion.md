# Fuentes turismo expansión (tanda 043) — nacional + internacional

Objetivo: sumar convocatorias de turismo (MinCIT avisos, EU Tourism Platform, UN Tourism). Runner: pytest (api), ruff. Investigación previa: MinCIT Turismo y Fontur ya cubiertos (mincit-innovacion apunta al listado; fontur-programas activo).

## Specs

- **S1** — Nueva fuente `mincit-avisos-convocatorias` (https://www.mincit.gov.co/temas-interes/avisos-convocatorias): feed de avisos con llamadas activas, ConfigurableHtml, con tests de seed + parse con fixture real.
- **S2** — Nueva fuente `eu-tourism-platform-calls` (https://transition-pathways.europa.eu/tourism/funding-and-support/funding-calls): agregador UE (Interreg, Horizonte Europa, fondos nacionales), ConfigurableHtml, con tests de seed + parse con fixture real.
- **S3** — Nueva fuente `un-tourism-calls` (https://www.untourism.int + https://tourism-villages.unwto.org/en): llamados ONU Turismo incl. Best Tourism Villages (recurrente anual), ConfigurableHtml, con tests de seed + parse con fixture real.
- **S4** — Spike de research (solo lectura, sin código): CTO-Caribe, OEA, CAF y otros candidatos; entrega shortlist rankeado para la próxima tanda.
- **S5** — Circuito producción: commit + push main, cherry a servidor, rebuild api (el reseed corre con código del contenedor), reseed, verify por fuente (runs con items > 0).

## Tasks

- [x] **T1** (inline) — S1: seed + `test_043_batch_seeds.py` + fixture parse MinCIT avisos. RED→GREEN. ✅ 2026-10-15
- [x] **T2** (inline) — S2: seed + tests + fixture EU platform. RED→GREEN. ✅ 2026-10-15
- [x] **T3** (inline) — S3: seed + tests + fixture UN Tourism (alcance BTV, decisión usuario). RED→GREEN. ✅ 2026-10-15
- [x] **T4** (inline) — S4: research CTO/OEA/CAF/otros, shortlist abajo. Sin código. ✅ 2026-10-15
- [x] **T5** (inline) — S5: commit `99ffd9a` + push + cherry `593cb20` a servidor (resolución manual: seed server recortado) + rebuild api + reseed (insert 0 / update 3, total 206) + verify live: mincit-avisos 8, eu-platform 5, un-villages 10 candidatos. ✅ 2026-10-15

## Log

- **L1** (pedido original, verbatim): "necesitamos incorporar más fuentes de convocatorias de turismo a nivel nacional e internacional"
- Cobertura existente verificada en seed: mincit-innovacion→convocatoriasturismo (listado), fontur-programas, procolombia (cat turismo), innpulsa, idt-experiencias-2026, world-bank, developmentaid.
- Alcance elegido por el usuario: MinCIT avisos + EU Tourism Platform + UN Tourism (+BTV) + investigar más (CTO y otros).
- BTV 2026 cerró 9-jun-2026; la fuente vale por recurrencia anual + Upgrade Programme.
- **T4 shortlist próxima tanda**: 1) Tourism Cares Grant Funds (tourismcares.org/grant-funds, grants reales a turismo comunitario) 2) UN Tourism Small Grants Programme (untourism.int, grants a iniciativas rurales; podría extender un-tourism-villages) 3) CTO scholarships (débil: awards/conferencias, verificar página de becas). Descambios: CAF (labs temáticos, sin página estable de turismo), BID Invest/BID Lab (financiamiento/VC, no convocatorias scrapeables).
