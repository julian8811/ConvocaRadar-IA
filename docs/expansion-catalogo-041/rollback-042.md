# Rollback X4 — integración reversible (issue #62)

Las 2 fuentes prioritarias (`eu-life-calls-cinea`,
`fundacion-biodiversidad-convocatorias`) siguen con seeds `enabled=False` y
`connector_config` de `configurable_html` (X2/X3). X4 NO tocó `seed.py`.

## Qué agregó X4 (y cómo revertirlo)

| Artefacto | Revert |
|---|---|
| `apps/api/app/connectors/eu_life_cinea.py` (nuevo, SIN `@register`, SIN import en `factory.py`) | borrar el archivo = runtime idéntico a X3 |
| `apps/api/app/connectors/fundacion_biodiversidad.py` (nuevo, idem) | borrar el archivo = runtime idéntico a X3 |
| `apps/api/tests/test_042_batch_sources.py` (nuevo, sin escrituras DB) | borrar el archivo |
| `docs/expansion-catalogo-041/piloto-041/` + `rollback-042.md` + `plan-activacion-etapas.md` | borrar los archivos |

Los conectores dedicados NO están cableados: `factory.connector_for()` sigue
devolviendo `ConfigurableHtmlConnector` para ambas keys (pin X3
`test_041_allowed_domains_families` lo protege; X4 no lo rompe porque los
módulos no se auto-registran).

## Cableado futuro (gate de activación, NO hacer ahora)

1. Importar ambos módulos en `factory.py` (efecto `@register`) O instancia
   directa en el runner, + cambiar `connector_type`/config en `seed.py`.
2. Ese cambio es el que convierte el gate: exige actualizar los pines
   `test_041_*` y `test_042_*` de `enabled False` + autorización del dueño.

## Rollback de una activación (si el gate la aprueba y algo sale mal)

1. Revert del commit que cambió `enabled` a `True` (las keys vuelven a
   `enabled=False`; el scheduler ignora fuentes deshabilitadas).
2. Si el conector dedicado da problemas en staging: quitar el import en
   `factory.py` → vuelve `ConfigurableHtmlConnector` automáticamente.
3. Sin migraciones, sin backfill, sin datos publicados que limpiar (las 041
   nunca escribieron DB: pines + cero escrituras en tests).
