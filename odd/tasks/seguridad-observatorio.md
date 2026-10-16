# Seguridad observatorio 10.3.1.128 — feature ODD

## Objective
Sacar la contraseña de `consultor.ceitto` del repo y auditar la superficie de seguridad de la plataforma viva (auth, registro, headers, rate-limit, cookies, secretos).

## Problem
1. La contraseña vigente del admin `consultor.ceitto@colmayor.edu.co` quedó escrita en claro en `odd/tasks/fuentes-cirugia-mayor.md:94` y en `.gstack/browse-audit.jsonl` (3 líneas), y el commit `1d8feaf` la dejó en historial.
2. Registro público abierto (`/observatorio/register` → `POST /api/v1/auth/register` crea org+usuario sin invitación).
3. CSP con restos cloud (`vercel.app`, `onrender.com`) y `connect-src` que no refleja la VM.
4. HTTP sin TLS en IP interna con HSTS ya emitido.

## Why
Pedido explícito del usuario: "pues sacalo tú. Verifica problema de vulnerabilidad y seguridad de la plataforma".

## Scope
- IN: redact del working tree; auditoría read-only viva (headers, auth, rate-limit, cookies, CORS) + lectura de código (auth, deps, rate_limit, CORS, cookies, register, seed); reporte con severidades y fixes propuestos.
- OUT: rewrite del historial git (destructivo — solo con autorización explícita aparte); rotación de la contraseña en el servidor (la hace el usuario o con orden expresa); cambios de código (solo propuesta).

## Tasks
- [x] T1 Localizar secreto en repo e historial
- [x] T2 Redactar secreto del working tree (este doc no lleva secretos)
- [x] T3 Auditoría viva + código
- [x] T4 Reporte con hallazgos y next steps

## Acceptance
- `grep` del password en claro limpio en working tree trackeado.
- Reporte con tabla de hallazgos (severidad, evidencia, fix).
- Sin commits ni pushes desde esta sesión salvo orden expresa.

## Findings (2026-10-15, read-only + redacción working tree)

Hecho: password redactado en `odd/tasks/fuentes-cirugia-mayor.md:94` y `.gstack/browse-audit.jsonl` (x3). Working tree limpio (grep exit 1). Queda en historial: commit `1d8feaf` — purge solo con orden expresa (destructivo) + rotar password en servidor.

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Alta | Password vigente en historial git | `git log -S` → `1d8feaf` |
| Alta | Registro público abierto (crea org+member sin invitación) | `auth.py:register` sin limiter ni gate; `/register` 200 |
| Media | Sin rate-limit en register (spam de orgs) | `auth.py` solo login/forgot tienen limiter 5/h |
| Media | `cookie_secure=True` por defecto sobre HTTP plano | `config.py:103`; Secure no persiste en http:// — confirmar `.env` del servidor |
| Media | CSP con dominios stale + `allow_methods/headers *` | header vivo `vercel.app`/`onrender.com`; `main.py:537-556` |
| Baja | Register `409` enumera emails (login/forgot no) | `auth.py` 409 vs 401 genérico / forgot constante |
| Baja | Divulgación de versiones + headers solo en API | `nginx/1.24.0`, `X-Powered-By: Next.js`; Next sin HSTS/nosniff |

Verificado OK: login 200/401 genérico, forgot constante + 5/h, CORS deny a `evil.example.com` sin eco ACAO, docs apagados (404), métodos no-POST en login 405, `/me` y `/admin` sin auth 401, JWT HS256 60min + scope check, `.env` vivo no trackeado.

## Progress
- 2026-10-15: login `consultor.ceitto@colmayor.edu.co` verificado 200 (contraseña sin punto final); `/me` admin; dashboard 1977/257; 207 fuentes; alerts pending 0. Rate-limit consumido 4/5 en la hora.
- 2026-10-15: doc creado. Espejo Engram pendiente.

## Next step
- T2: redact + T3 auditoría.
