# Manejo de versiones de ConvocaRadar IA

Este proyecto usa versionado semantico.

## Esquema

- `MAJOR` cuando hay cambios incompatibles o una reestructuracion fuerte.
- `MINOR` cuando se agregan funciones nuevas sin romper lo existente.
- `PATCH` cuando se corrigen errores o detalles menores.

Ejemplos:

- `v0.1.0` primer corte funcional.
- `v0.2.0` nuevas fuentes, mejores reportes, mejoras de scraping.
- `v0.2.1` correcciones de UI o bugs menores.

## Flujo recomendado en GitHub

1. Trabaja en una rama por cambio:
   - `feature/scraping-reales`
   - `fix/login-auth`
   - `chore/deploy-render`
2. Abre pull request contra `main`.
3. Deja que corran los checks de GitHub Actions.
4. Cuando el PR se fusiona, crea un tag semantico:
   - `v0.1.1`
   - `v0.2.0`
5. Publica el release en GitHub con ese tag.

## Regla práctica

- Si cambias infraestructura, despliegue o seguridad, documentalo en el release.
- Si cambias scraping, IA o reportes, agrega notas de impacto porque son las partes que mas se rompen.
- Si cambias base de datos, acompana la version con migracion clara.

## Convencion de commits

Sugerida:

- `feat:` nueva funcionalidad
- `fix:` correccion
- `chore:` mantenimiento
- `docs:` documentacion
- `refactor:` refactor sin cambio funcional
- `test:` pruebas
- `ci:` integracion continua

