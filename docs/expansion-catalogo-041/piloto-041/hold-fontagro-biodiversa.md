# HOLD intacto — FONTAGRO y Biodiversa+ (X4, issue #62)

Sin código, sin cambios de seed, sin tests nuevos para estas dos fuentes en X4.
Seeds `enabled=False` + `tier experimental` intactos (verificados por pines X3
en `test_041_batch_seeds.py`, no duplicados aquí).

## FONTAGRO (`fontagro-convocatorias`)

- Estado: HOLD. Ciclo anual; al cierre de X3 la ventana vigente era la
  Convocatoria 2027 (cierre por edición, "desconocido" en matriz).
- Para activar después: guardar HTML real de `/es/iniciativas/convocatorias`,
  confirmar fecha de cierre de la edición vigente y elegibilidad
  (consorcios multi-país LatAm/Caribe), luego conector + tests espejo de X4.

## Biodiversa+ (`biodiversa-calls`)

- Estado: HOLD. Joint Call BiodivFuture 2026-2027 verificada abierta en X1
  (pre-proposals hasta 2026-11-10).
- Para activar después: revalidar elegibilidad por agencia financiadora
  nacional (¿aplica Colombia como asociado internacional?) antes de indexar;
  luego HTML real + conector + tests espejo de X4.
