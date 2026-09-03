# Security Policy

## Reportar una vulnerabilidad

No abras un issue público. Usá uno de estos canales (en orden de preferencia):

1. **GitHub Security Advisory**: `Security` → `Report a vulnerability` en https://github.com/julian8811/ConvocaRadar-IA/security/advisories/new
2. **Mail institucional**: `security@convocaradar.com` (o `julianmontoya8811@gmail.com` como respaldo)

Incluí:

- Descripción del problema
- Pasos para reproducir
- Impacto estimado

Responderemos dentro de 72h. Ver también `security@convocaradar.com` y la pestaña GitHub Advisory para triage privado.

## Buenas prácticas del repo

- Nunca commitear `.env` ni secretos. Usá `.env.example` como plantilla.
- Ejecutá `bash scripts/check-secrets.sh` antes de pushear.
- Las claves `JWT_SECRET`, `INTERNAL_API_KEY` y `RESET_TOKEN_SECRET` deben tener al menos 32 caracteres; la app no inicia si no se cumple.
- En producción, configurá `SENTRY_DSN` y revisá `docs/restore-runbook.md` para backups/restore.

## Rotación de secretos

Ver `scripts/check-secrets.sh` y `.env.production.example`.
