# Changelog

## [0.2.0] - Unreleased

### Added

- Plan de despliegue con Vercel, Neon, Upstash, R2 y Render.
- Blueprint base de Render para API y worker.
- Guia de versionado semantico y flujo GitHub.
- Plantilla de variables de produccion.
- Nuevo endpoint `GET /opportunities/{id}/url-check` que devuelve `{"official_url": bool, "application_url": bool}`.

### Changed

- **Breaking**: Se eliminaron `official_url_is_reachable` y `application_url_is_reachable` del schema `OpportunityRead`. Ya no se serializan al listar oportunidades (elimina N+1 HTTP requests). Usar `GET /opportunities/{id}/url-check` en su lugar.

