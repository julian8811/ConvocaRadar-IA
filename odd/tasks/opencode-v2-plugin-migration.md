# Feature: opencode-v2-plugin-migration

## Objective
Dejar el TUI/Server en verde y migrar todos los plugins V1 a API V2.

## Problem
Todos los plugins usan SDK V1 (`@opencode-ai/plugin` 1.x) sobre runtime V2 (2.0.26):
- 8 locales en `~/.config/opencode/plugins/` fallan (stage=prepare).
- 2 paquetes TUI (`opencode-subagent-statusline`, `opencode-sdd-engram-manage`) fallan con `NpmInstallFailedError`.
- 1 TUI local `tui-plugins/gentle-logo.tsx` usa `TuiPlugin` V1.
- V2 exige `from "@opencode/plugin"` + `Plugin.define({id, setup})`. V1 no corre en V2 (migration guide).

## Why
Sin esto cada arranque reconcilia 12 plugins y falla todo; bloquea sesiones y TUI.

## Scope
- `~/.config/opencode/cli.json` (plugins TUI)
- `~/.config/opencode/plugins/` (8 files)
- `~/.config/opencode/tui-plugins/gentle-logo.tsx`
- `~/.config/opencode/package.json` (deps V1)
- Docs: https://opencode.ai/v2/docs/build/plugins + https://opencode.ai/v2/docs/build/plugins/migrate-v1

## Constraints
- No `bun install`/`npm install` a ciegas; verificar compat V2 primero.
- Backups de `cli.json`/`package.json` antes de tocar.
- Un task = un commit unidad si fuera repo; aquí son dotfiles → backup + verificación por task.
- No inventar nombres de hooks V2; validar contra docs/migrate-v1.

## Checklist
- [x] T1-unblock: desactivar plugins rotos, TUI en verde (route: inline)
- [x] T2-trivial: migrar 5 triviales a V2 (herdr-agent-state.js, model-variants.ts, rtk.ts, skill-registry.ts, telemetry-runtime.ts) (route: delegated direct, 1 writer)
- [x] T3-moderate: migrar engram.ts + sdd-task-result-artifacts.ts (route: delegated direct, 1 writer)
- [x] T4-deep: rewrite opencode-review-transport.ts + TUI (gentle-logo.tsx + 2 paquetes npm: chequear reemplazo V2 o port) (route: delegated direct, 1 writer)
- [x] T5-reactivate: reactivar + `opencode plugin list` limpio + TUI sin failed (route: inline verify)

## Authorized scope
Estrategia elegida por el usuario: desbloquear y migrar por etapas. T1 puede desactivar temporalmente.

## Acceptance criteria
- `opencode plugin list` sin errores y con versiones/IDs V2.
- TUI Plugins screen sin `failed`.
- Cada plugin migrado importa `@opencode/plugin` y exporta `Plugin.define`.
- `bun install --dry-run` / `opencode service status` OK.

## Applicable checks
- `opencode plugin list --log-level debug --print-logs | tail`
- `opencode service status`
- `bun install --dry-run` en `~/.config/opencode`
- Spot-check TUI screenshot del usuario.

## Progress
- 2026-10-11: creado doc, 5 tasks. Mapeo explorer: 5 triviales, 2 moderados, 1 profundo. Causa raíz V1-vs-V2 confirmada.
- T1: done. Backups: cli.json.bak-20261011; 8 files en plugins.disabled/. `opencode plugin list` → "No plugins found", service healthy, sin nuevos NpmInstallFailedError tras el cambio.
- T2: done. 5 triviales en V2 con @opencode/plugin@2.0.26, los 5 listados como local, cero errores.
- T3: done. engram.ts + sdd-task-result-artifacts.ts en V2, 7/7 locales listados, cero errores. (Engram mirror: pending — save rechazado por sesiones runtime duplicadas tras el restart; reintentar con mem_session_start.)
- T4: done. review-transport reescrito en V2 (8/8 locales listados, cero errores nuevos). gentle-logo portado (carga limpio, sin slot de logo en V2). Ambos paquetes npm TUI confirmados V1-only upstream → siguen desactivados.
- T5: done. Usuario confirmó TUI todo verde. (Engram mirror: pending por el mismo motivo.)

## Verification evidence
- `opencode service status` → sano.
- `opencode plugin list` → "No plugins found", sin errores.
- Log: último `plugin operation failed` es el viejo previo al cambio; nada nuevo.
- Usuario confirmó TUI limpio ("ya quedaron los plugins").

## Next step
- T1 cerrado. T2–T4 (migración V2) quedan pendientes en este doc para cuando quieras retomarlos.
