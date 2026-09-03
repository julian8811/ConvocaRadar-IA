# Security Policy

## Reportar una vulnerabilidad

No abras un issue público. Enviá un mail a `julianmontoya8811@gmail.com` con:

- Descripción del problema
- Pasos para reproducir
- Impacto estimado

Responderemos dentro de 72h.

## Buenas prácticas del repo

- Nunca commitear `.env` ni secretos. Usá `.env.example` como plantilla.
- Ejecutá `bash scripts/check-secrets.sh` antes de pushear.
- Las claves `JWT_SECRET`, `INTERNAL_API_KEY` y `RESET_TOKEN_SECRET` deben tener al menos 32 caracteres; la app no inicia si no se cumple.
- En producción, configurá `SENTRY_DSN` y revisá `docs/restore-runbook.md` para backups/restore.

## Rotación de secretos

Ver `scripts/check-secrets.sh` y `.env.production.example`.
