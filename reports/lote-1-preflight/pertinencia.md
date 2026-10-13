# Pertinencia — lote 1 preflight (issue #59)

## Método (se aplica en el piloto L3, 1 GET reutilizado por fuente)

Del único cuerpo descargado se extraen hasta 10 títulos (`extract_titles`,
cubierto por tests e2e con stub). Cada título se clasifica:

- **accionable**: convocatoria/beca/fondo abierto con entidad y cierre o
  criterio de elegibilidad visible (sirve para crear ficha).
- **editorial**: noticia/opinión/agenda sin llamado abierto (ruido a filtrar).
- **ambigua**: posible llamado pero sin datos suficientes (requiere revisión).
- **empleo-otro**: ofertas laborales u otro contenido fuera de misión.

Precisión aparente = % accionable sobre la muestra, SOLO como estimación de
muestra (no certifica la fuente). `needs_human_review=true` mientras no se
acredite relevancia con títulos reales.

## Estado en preflight (0 red): priors por catálogo, todos pendientes

| fuente | prior | motivo del prior | títulos reales | veredicto |
|--------|-------|------------------|----------------|-----------|
| novo-nordisk-grants | alta | endpoint WP dedicado a grants (health/biotech/research) | pendientes L3 | needs_human_review |
| grants-gov-forecast | alta | RSS dedicado a forecast de oportunidades, no noticias | pendientes L3 | needs_human_review |
| minciencias | alta | página dedicada /convocatorias/todas del ente rector | pendientes L3 | needs_human_review |
| ukri-opportunities | alta | buscador dedicado de oportunidades de financiamiento | pendientes L3 | needs_human_review |
| innpulsa | alta | API dedicada con filtro active_only=true | pendientes L3 | needs_human_review |

Ninguna fuente se declara pertinente sin sus 10 títulos reales clasificados.
UNKNOWN antes que certificar.
