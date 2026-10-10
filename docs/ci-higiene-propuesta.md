# Propuesta de higiene CI (T7) — SIN APLICAR

Estado: propuesta documentada, ningún workflow ni config fue modificado.
La aplicación futura requiere decisión explícita del usuario, por propuesta o en el orden sugerido al final.

## Ruta rápida

1. Aplicar propuesta 1 (dummy secrets vía `env:`) — cambio mecánico, verificable por diff de `compose config`.
2. Aplicar propuesta 2 (frozen lockfile en Vercel) — requiere verificar dónde instala Vercel antes de cambiar el flag.
3. Aplicar propuesta 3 (ratchet de ruff) por fases, una fase por commit, sin bajar nunca el nivel exigido.
4. Verificación global: `bash scripts/check-secrets.sh` + CI verde en rama + `git diff --name-only` limitado a lo esperado.

## Propuesta 1 — Dummy secrets vía `env:` del job en vez de `sed -i` sobre `.env`

### Problema

El job `server-smoke` escribe valores con forma de secreto en un fichero del disco con nueve comandos `sed -i` (`.github/workflows/ci.yml:176-184`), mientras que todos los demás jobs que necesitan dummies ya usan `env:` a nivel de job o de paso (`ci.yml:41-44` compose-lint, `ci.yml:96-99` prod-asserts, `ci.yml:129-131` test, `ci.yml:152-155` docker).
El `sed -i` es el único punto de CI que muta un fichero para inyectar secretos: deja un `.env` con credenciales en el disco del runner (persiste si el runner se reutiliza), es frágil ante cambios en los nombres de clave del template y mezcla dos mecanismos para el mismo fin.

### Cambio exacto propuesto (ilustrativo, NO aplicado)

```diff
   server-smoke:
     runs-on: ubuntu-latest
     env:
       COMPOSE_PROJECT_NAME: convocaradar-ci
       COMPOSE_FILE: docker-compose.server.yml
+      POSTGRES_PASSWORD: T7nQ4mK9xV2pL8rC5hJ6sW3zD1fG
+      DATABASE_URL: postgresql+psycopg://convocaradar:T7nQ4mK9xV2pL8rC5hJ6sW3zD1fG@postgres:5432/convocaradar
+      MINIO_ROOT_PASSWORD: R8vD3kN6qW1mX9tL4pH7cJ2sF5zG
+      S3_SECRET_KEY: R8vD3kN6qW1mX9tL4pH7cJ2sF5zG
+      JWT_SECRET: Q4mZ8rT2vK7pD5nX1cH9sL6wF3jN8bR5
+      INTERNAL_API_KEY: V9xK3mQ7dT1pR8nL5cJ2sH6wF4zN7bD9
+      RESET_TOKEN_SECRET: N6rW2pT8xK4mD9vL1cH7sQ5jF3zG
+      BOOTSTRAP_SOURCES_ON_STARTUP: "false"
       - name: Prepare production-like non-secret environment
         run: |
           cp .env.production.example .env
-          sed -i 's|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=T7nQ4mK9xV2pL8rC5hJ6sW3zD1fG|' .env
-          sed -i 's|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://convocaradar:T7nQ4mK9xV2pL8rC5hJ6sW3zD1fG@postgres:5432/convocaradar|' .env
-          sed -i 's|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=R8vD3kN6qW1mX9tL4pH7cJ2sF5zG|' .env
-          sed -i 's|^S3_SECRET_KEY=.*|S3_SECRET_KEY=R8vD3kN6qW1mX9tL4pH7cJ2sF5zG|' .env
-          sed -i 's|^JWT_SECRET=.*|JWT_SECRET=Q4mZ8rT2vK7pD5nX1cH7sQ5jF3zG|' .env
-          sed -i 's|^INTERNAL_API_KEY=.*|INTERNAL_API_KEY=V9xK3mQ7dT1pR8nL5cJ2sH6wF4zN7bD9|' .env
-          sed -i 's|^RESET_TOKEN_SECRET=.*|RESET_TOKEN_SECRET=N6rW2pT8xK4mD9vL1cH7sQ5jF3zG|' .env
-          sed -i 's|^BOOTSTRAP_SOURCES_ON_STARTUP=.*|BOOTSTRAP_SOURCES_ON_STARTUP=false|' .env
-          sed -i 's|^WEB_PORT=.*|WEB_PORT=3001|' .env
           docker compose --env-file .env config > /dev/null
```

Notas del diff: se reutilizan los mismos valores dummy actuales (cero secretos nuevos); `DATABASE_URL` se declara completa en `env:` porque incrusta la contraseña y no puede interpolarse desde el fichero; el `sed` de `WEB_PORT` ya era un no-op (el template trae `WEB_PORT=3001` en `.env.production.example:91`) y desaparece sin efecto.
Base técnica: con `--env-file`, las variables presentes en el entorno del proceso tienen precedencia sobre las del fichero en la interpolación de compose, por lo que el `config` renderizado debe ser idéntico.

### Riesgo y rollback

Riesgo bajo. El único riesgo real es una discrepancia de precedencia entre entorno y `--env-file` en alguna versión de compose, que se manifestaría como un `config` distinto. Rollback: revertir el commit del workflow restaura los nueve `sed -i` sin tocar ningún otro job.

### Verificación sugerida

1. En la rama de aplicación, capturar `docker compose --env-file .env config` antes y después del cambio y exigir diff vacío.
2. CI verde en el job `server-smoke`.
3. `bash scripts/check-secrets.sh` (exit 0) y confirmación de que ningún `.env` con dummies queda trackeado (`git status --short`).

## Propuesta 2 — Volver a frozen lockfile en Vercel (o justificar por escrito no hacerlo)

### Problema

`vercel.json:3` fija `pnpm install --no-frozen-lockfile`, mientras que CI instala con `pnpm install --frozen-lockfile` (`ci.yml:145`). El deploy y CI pueden resolver dependencias distintas: lo que pasa CI no es necesariamente lo que corre en producción.
El mapa de lockfiles agrava el cuadro: existe `pnpm-lock.yaml` en la raíz (186 KB) pero no existe `apps/web/pnpm-lock.yaml`, y el proyecto Vercel usa Root Directory `apps/web` (nota en `deploy.yml:120-121`). Un `--frozen-lockfile` a ciegas falla si el directorio de instalación no tiene lockfile resoluble.

### Cambio exacto propuesto (ilustrativo, NO aplicado)

Prerrequisito obligatorio antes del cambio: confirmar en un deploy de preview desde qué directorio instala Vercel (raíz del repo vs `apps/web`).

- Si instala desde la raíz (donde hay lockfile, y CI ya demuestra que frozen funciona):

```diff
 {
   "outputDirectory": ".next",
-  "installCommand": "pnpm install --no-frozen-lockfile"
+  "installCommand": "pnpm install --frozen-lockfile"
 }
```

- Si instala dentro de `apps/web` (sin lockfile propio): primero generar `apps/web/pnpm-lock.yaml` (o mover el Root Directory a la raíz con build filtrado a `@convocaradar/web`), y solo después cambiar el flag. Sin lockfile resoluble, el flag rompe el deploy; ese es el orden correcto.

Alternativa documentada (si hay razón de plataforma para no congelar): no cambiar el flag y registrar en `DEPLOYMENT.md` el porqué (p. ej. resolución gestionada por Vercel), con fecha y responsable. El silencio actual —flag sin explicación— es lo que esta propuesta quiere eliminar, en un sentido o en el otro.

### Riesgo y rollback

Riesgo medio: un frozen mal ubicado rompe el deploy de Vercel (build rojo, producción intacta hasta el próximo deploy exitoso). Mitigación: aplicar en preview primero, nunca directo en producción. Rollback: revertir `vercel.json` a `--no-frozen-lockfile` restaura el comportamiento actual en el siguiente deploy.

### Verificación sugerida

1. Deploy de preview con el flag: build verde y bytecode de dependencias idéntico entre dos deploys consecutivos sin cambios.
2. `pnpm install --frozen-lockfile` reproducible en local desde el mismo directorio que usa Vercel.
3. Si se elige la alternativa, revisión del párrafo de justificación en `DEPLOYMENT.md` (qué se decidió, por qué, cuándo).

## Propuesta 3 — Plan ratchet de ruff por fases

### Problema

`apps/api/pyproject.toml:69` limita ruff a `select = ["E9", "F63", "F7", "F82"]` (solo corrección ejecutable: sintaxis, flujo inválido, nombres indefinidos), con el comentario de deuda en `pyproject.toml:65-68` que declara la intención de endurecer por separado. El gate de CI (`ci.yml:113-114`, `ruff check .`) hereda ese mínimo: hoy bloquea defectos de runtime pero deja pasar deuda de estilo sin plan de cierre. Sin ratchet, la deuda solo puede crecer.

### Cambio exacto propuesto (ilustrativo, NO aplicado)

Ratchet = subir el nivel exigido por fases, una fase por commit, sin bajar nunca lo ya exigido. Orden sugerido:

- Fase 1 (actual, sin cambio): `E9, F63, F7, F82` — corrección ejecutable.
- Fase 2: pyflakes completo (`F`), que atrapa imports sin usar y variables muertas sin imponer estilo:

```diff
 [tool.ruff.lint]
-select = ["E9", "F63", "F7", "F82"]
+select = ["E9", "F"]
```

- Fase 3: errores pycodestyle (`E`, excluyendo `E501` si la deuda de línea larga es grande) + `per-file-ignores` acotados como trinquete por slice de directorio.
- Fase 4: reglas plenas (`E501`, `I` de isort y resto) por slices, cerrando los `per-file-ignores` a medida que cada slice se limpia.

Dimensionar cada fase antes de aplicarla con `ruff check --statistics` sobre `apps/api` para saber cuántas violaciones introduce y si caben en un commit revisable (~400 líneas orientativas); si una fase excede, se parte por slices de directorio con `per-file-ignores` temporales y explícitos.

### Riesgo y rollback

Riesgo bajo-medio: cada fase puede revelar cientos de violaciones preexistentes y tentar un commit gigante o un `noqa` masivo. Regla del plan: ningún commit baja el nivel exigido ni añade `noqa`/ignores sin fecha y sin slice asignado. Rollback por fase: revertir el commit de la fase devuelve ruff al nivel anterior; los `per-file-ignores` de slices ya limpios se conservan porque solo restringen, nunca relajan.

### Verificación sugerida

1. Por fase: `ruff check .` verde en `apps/api` + `pytest tests/ -q` verde (la fase no debe romper tests).
2. `ruff check --statistics` antes/después publicado en el cuerpo del commit o del PR para mostrar la deuda cerrada.
3. `bash scripts/check-secrets.sh` como higiene habitual del commit.

## Orden de aplicación sugerido

| Orden | Propuesta | Motivo |
|-------|-----------|--------|
| 1.º | Dummy secrets vía `env:` | Mecánica, riesgo bajo, verificación por diff vacío de `compose config`. |
| 2.º | Frozen lockfile en Vercel | Requiere el prerrequisito del directorio de instalación; preview primero. |
| 3.º | Ratchet de ruff por fases | Trabajo incremental largo; empieza cuando 1 y 2 estén cerradas para no mezclar frentes. |

## Queda fuera de este slice

- Los flakes preexistentes admitidos en `deploy.yml:30-32` (gate `ci-status` + bypass por `workflow_dispatch` mientras se corrigen los tests inestables): problema real, pero de otro slice; esta propuesta no los toca.
- Rotación o gestión de secretos reales (Render, Vercel, SMTP): fuera de alcance; aquí solo se mueven dummies con forma de secreto dentro de CI.
- `CNAME`, `render.yaml`, migraciones y cualquier operación en el servidor universitario: excluidos por el scope del feature.
