# Desarrollo reproducible

## Requisitos

- Docker Desktop con integración WSL2.
- `make` (o ejecutar los comandos equivalentes de `Makefile`).
- Copiar `.env.example` a `.env` y completar los secretos; nunca subir `.env`.

## Flujo diario

```sh
make up       # construye imágenes y levanta servicios
make health   # comprueba API y frontend
make lint     # Ruff + ESLint
make test     # pruebas backend y frontend
make migrate  # aplica migraciones Alembic
make logs     # logs recientes
```

Las migraciones son la única fuente de verdad del esquema. No se deben editar tablas manualmente en entornos compartidos. Antes de operaciones destructivas, ejecutar `make backup`.

## Arquitectura

- `apps/api/app/api/v1`: endpoints HTTP y validación de permisos.
- `apps/api/app/services`: casos de uso y exportaciones.
- `apps/api/app/connectors`: adaptadores de fuentes externas.
- `apps/api/migrations`: cambios versionados de base de datos.
- `apps/web/app`: rutas y pantallas Next.js.
- `apps/web/components`: componentes reutilizables.

Los conectores no deben escribir directamente en la interfaz; deben devolver datos normalizados. Las variables sensibles se leen desde `Settings` y se inyectan por Docker.
