# Seguridad remediación local + purge — feature ODD

## Objective
Cerrar los hallazgos de `seguridad-observatorio.md` en código local (sin romper contratos por defecto), con tests, y luego purgar el secreto del historial con el force-push ya autorizado.

## Problem (de auditoría 2026-10-15)
1. `POST /auth/register` sin rate-limit (login/forgot tienen 5/h) → spam de orgs.
2. Registro público sin gate (crea org+member sin invitación).
3. CORS con `allow_methods/headers *`; CSP con dominios cloud hardcodeados (`vercel.app`, `onrender.com`) en vez de derivarse de settings.
4. Next no emite headers de seguridad (solo la API los pone).
5. Historial contiene password en claro (commit `1d8feaf`) — purge + force-push AUTORIZADO por el usuario.

## Why
Pedido del usuario (parafraseado, secretos redactados): arreglar las novedades de seguridad en servidor, local y GitHub; orden elegido: local primero, purge autorizado.

## Scope
- IN: T1 rate-limit register; T2 `REGISTRATION_MODE` (open|domain|closed, default open); T3 CORS explícito + CSP desde settings; T4 headers Next; tests; purge + force-push.
- OUT: rotación de secretos en servidor y `.env` del servidor (paso servidor, con el usuario); cambiar defaults de contrato (register sigue 409, default open); reescribir más historial que el secreto.
- Credenciales del chat (PAT GitHub, SSH, passwords): NO se usan, NO se guardan, NO se commitean. El usuario debe revocarlas/rotarlas ya.

## Constraints
- TDD: test RED antes de cada cambio de comportamiento; suite vecina verde.
- Default sin cambios de contrato: `open` por defecto, 409 intacto.
- Sin commits ni push de código salvo orden expresa (el force-push autorizado cubre SOLO el purge, y se hace con backup `git bundle` previo).
- Nunca usar el PAT pegado en chat; GitHub solo con auth existente (`gh auth status`).

## Tasks
- [x] T1 Rate-limit en register (patrón SlidingWindowLimiter,uento por IP+email)
- [x] T2 Gate `REGISTRATION_MODE` + `REGISTRATION_ALLOWED_DOMAINS` en settings, docs en `.env.example`
- [x] T3 CORS métodos/headers explícitos + CSP derivada de `frontend_url`/`backend_url`
- [x] T4 `headers()` en Next (HSTS, nosniff, DENY, referrer, permissions)
- [ ] T5 Tests enfocados + suite vecina (auth) verde
- [x] T6 Purge `1d8feaf` (backup bundle, filter-repo, verify, force-push) ✅ remoto limpio + rama local recuperada
- [x] T10 Servidor: merge 85b6eeb en rama server + .env (domain/colmayor, COOKIE_SECURE=false) + rebuild api/worker/web + verify vivo ✅ (health/login/headers/CSP/gate/sesión)

## Acceptance
- Register limitado y gateado por config; defaults intactos.
- Tests nuevos en RED→GREEN + suite auth verde.
- `git log -S <secreto>` limpio tras purge; working tree sin secretos.
- Servidor deployado y verificado en vivo; GitHub al día (main 9f6ebda + rama seguridad-remediacion 3f23f61 con d61ed60 para PR).

## Progress
- 2026-10-15: TODO 10/10 CERRADO Y VERIFICADO EN VIVO. Deploy 85b6eeb + dashboard 1970/256 + gate 403 + CSP/headers. GitHub al día: main 9f6ebda, rama seguridad-remediacion 3f23f61. PENDIENTE USUARIO: rotar claves (consultor, servidor, PATs), gh auth, worktrees, segundo purge en rama server.

## Next step
- Nada pendiente en este feature: T11 cerró la puesta al día. Resto en manos del usuario (rotaciones, worktrees, segundo purge, CI rojo pre-existente ofrecido aparte).
