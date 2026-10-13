# Plan de activación por etapas — gate 041/042 (issue #62)

Precondición: autorización expresa del dueño + rama `expansion-catalogo-041`
sin mergear. Cada etapa tiene criterio GO/NO-GO; un NO-GO detiene sin tocar
las demás fuentes.

## Etapa 0 — Revalidación offline (sin red de scraping)

- [ ] Confirmar que los deadlines sintéticos de los fixtures X4 coinciden con
  los portales (LIFE: ¿sigue vigente SAP Nature? FB: fechas BOE/bases reales).
- GO: fechas reales ≥ hoy para al menos 1 convocatoria por fuente.

## Etapa 1 — Staging dry-run (1 GET por portal, UA del repo, secuencial)

- [ ] `eu-life-calls-cinea`: dry-run del conector dedicado contra HTML vivo;
  comparar títulos extraídos vs `evidencia-piloto-041.json`.
- [ ] `fundacion-biodiversidad-convocatorias`: idem.
- GO: ≥1 candidato abierto real por fuente, 0 ruido (empleo/noticias) en la
  muestra, close_dates parseadas (no todas None).
- NO-GO típico: cambio de markup → actualizar selectores + fixtures + tests.

## Etapa 2 — Cableado reversible en staging

- [ ] Import en `factory.py` + `seed.py` sigue `enabled=False`; verificar que
  `connector_for()` devuelve el dedicado (test temporal, luego pin definitivo).
- [ ] Activar UNA fuente (`enabled=True`) en staging, barrido supervisado,
  revisar oportunidades persistidas (pertinencia + duplicados vs catálogo).
- GO: 0 duplicados semánticos, 0 vencidas publicadas, 0 ruido.
- Rollback: revert del commit de `enabled` (ver `rollback-042.md`).

## Etapa 3 — Segunda fuente + decisión Fondo Acción / HOLDs

- [ ] Repetir etapa 2 para la segunda prioritaria.
- [ ] Fondo Acción: solo tras guardar HTML real + conector con pin
  procurement (ver `piloto-041/fondo-accion-revision-humana.md`).
- [ ] FONTAGRO / Biodiversa+: solo tras levantar su HOLD con evidencia nueva.

## Criterios GO globales (todas las etapas)

1. Seeds en prod: `enabled=False` hasta el GO explícito por fuente.
2. `tier experimental` hasta primera verificación en staging.
3. Cero escrituras DB en tests (pines AST + parse offline).
4. Sin tocar remediación #61, sin cron nuevo, sin deploy fuera del runbook.
