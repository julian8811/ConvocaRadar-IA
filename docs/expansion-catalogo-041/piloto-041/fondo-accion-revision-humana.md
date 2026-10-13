# Fondo Acción — revisión humana (X4, issue #62)

**Decisión X4: SIN conector definitivo.** Evidencia ordenada para que el dueño
decida en el gate. Cero red, cero código para esta fuente en X4.

## Qué dice la evidencia existente (X1–X3)

- Portal: `https://fondoaccion.org/convocatorias/` (HTTP 200 verificado en X1).
- Seed: `fondo-accion-convocatorias`, `enabled=False`, `tier experimental`,
  `configurable_html` con selectores anclados a `/convocatorias`.
- Patrón documentado: **mezcla convocatorias de proyecto con consultorías
  procurement** en la misma página.
  - Proyecto (GO): "Becas Laboratorio Acciones Escolares Climáticas CSIELO"
    (`/2026/08/12/lab-csielo-convocatoria/`, cierre 2026-10-15), "Territorios Más
    Sostenibles" (11 proyectos, 2000M COP; edición 2025-03 cerrada, patrón anual).
  - Ruido conocido: consultorías/procurement listadas junto a las convocatorias.
- Pertinencia: títulos de proyecto contienen `convocatoria|becas|laboratorio|
  territorios`; el ruido contiene `consultor|términos de referencia|oferta`.
- Vigencia: TMS 2025-03 está cerrada; CSIELO cerraba 2026-10-15 (al 2026-10-13
  seguía vigente por 2 días — revalidar en el gate).

## Qué falta verificar (bloquea el conector definitivo)

1. **Regla de separación proyecto vs consultoría**: confirmar con un HTML real
   guardado que los anchors de proyecto viven bajo `/convocatorias/` y los de
   procurement bajo otra ruta (o marcador textual estable). Sin ese HTML, el
   selector sería una adivinanza.
2. **Frecuencia real**: el patrón es intermitente/anual; confirmar que `weekly`
   no genera barridos vacíos sistemáticos (o pasar a `monthly`).
3. **Fecha de cierre legible**: verificar formato de fecha en las cards
   (¿"Cierre:"? ¿rango? ¿solo año?) para el filtro de vencidas.
4. **Elegibilidad**: confirmar "organizaciones colombianas" como regla
   (¿personas naturales? ¿entidades públicas?) para no indexar inaplicables.

## Propuesta para el gate

- Guardar 1 HTML real sanitizado de `/convocatorias/` (paso con red explícita,
  fuera de X4) y versionarlo aquí como `fixture-fondo-accion.html`.
- Con ese HTML, escribir el conector dedicado con pin procurement
  (títulos/URLs de consultoría → descartados) + tests espejo de `test_042`.
- Hasta entonces: seed `enabled=False` intacto, sin código.
