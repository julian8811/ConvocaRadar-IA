# Plataforma: conectar lo que falta — feature ODD

## Objective
Cerrar la brecha entre plataforma y operación real: que las alertas lleguen (email), que el panel se actualice solo y que los perfiles muestren datos reales. Sin reescribir lo que ya está cableado.

## Problem (evidencia de auditoría 2026-10-12)
No hay datos mock en `apps/web` (grep limpio salvo UX legítimo). Lo hallado:

1. **Alertas no llegan**: CRUD + scheduler cableados (`alerts.py:76-272`, `main.py:96-101`), pero `core/email.py:38-43` retorna `dry_run=True` sin `resend_api_key` ni `smtp_host`: todo pasa a `sent` sin salir ningún correo. `pending_alerts=0` es el síntoma visible.
2. **Panel "desactualizado"**: cableado real (`dashboard.py:239,260,281` → Triage/Pipeline/Health zones), pero confluyen: cache 60s en `/dashboard/health` (`dashboard.py:288-294`), sin polling (`useQuery` sin `refetchInterval`), y filtros `_visible_opportunity` que recortan por diseño (`dashboard.py:119-130`).
3. **Perfiles muestran defaults**: `onboarding/page.tsx:116-119` inicializa `useState` con query aún en loading; los TagSelector quedan en `["COP","USD"]`/`["LatAm"]` aunque el perfil tenga otros valores. Bug UI, no mock.
4. **Ausencias (no mocks, features inexistentes)**: sin pantalla de perfil de usuario propio; sin gestión de usuarios en admin (solo rol). Solo si el usuario las pide.

## Why
Pedido explícito: revisar qué es mock y conectar lo que no sirve (alertas, perfiles, administración, panel).

## Scope
- IN: T1 email delivery, T2 auto-refresh panel, T3 fix tags onboarding. Tests donde aplique; verify en servidor.
- OUT: gestión de usuarios y perfil propio (features nuevas, solo con autorización); SSE/websockets (si con polling basta); tocar scraping.
- Secretos (SMTP/Resend): solo server-side, los provee el usuario, rotación al cierre como siempre.

## Constraints
- TDD proporcional en cambios de código; fixes UI con verificación visual (Playwright) si aplica.
- `.env` del servidor solo se toca con autorización explícita por valor (qué var, sin exponer valores en repo/memoria/chat más allá de lo imprescindible).
- Commits Conventional; deploy patrón E19–E24. Push/merge los decide el usuario.

## Tasks
- [x] **T1 (P0)** ✅ 2026-10-12 Resend configurado + envío real + **confirmación visual en bandeja por el usuario** (screenshot). Criterio cumplido.
- [ ] **T2 (P1 writer)**
- [x] **T2 (P1 writer)** ✅ 2026-10-12 Auto-refresh + deployado (cherry `22af30c`, web healthy). Verificación visual pendiente por el usuario.
- [x] **T3 (P1 writer)** ✅ 2026-10-12 Tags hidratados + deployado. Verificación visual pendiente por el usuario.
- [ ] **T4 (P2, solo si se pide)** Gestión de usuarios / perfil propio: propuesta antes de código.

## Acceptance
- Correo de prueba llega de verdad (no dry-run).
- Panel refleja un sweep terminado sin F5 manual (≤60s + polling).
- Onboarding muestra los valores reales del perfil.
- Suite verde, sin regresiones.

## Progress
- 2026-10-12: doc creado con auditoría read-only (sin código tocado). Mirror Engram pendiente.

## Next step
- Orden de ejecución + credencial SMTP/Resend para T1.
