# syntax=docker/dockerfile:1.7
# ── Stage 1: install deps + build the Next.js app ────────────────────────────
# The repo is a pnpm workspace (root package.json pins pnpm@10.7.0 via
# packageManager; the single shared lockfile lives at the repo root, matching
# CI). Build context is the repository root.
FROM node:22-slim AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

RUN corepack enable && corepack prepare pnpm@10.7.0 --activate

# Workspace manifests first for better layer caching (frozen lockfile
# validates against the root + apps/web importers only).
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile --ignore-scripts

# NEXT_PUBLIC_* vars are embedded at build time by Next.js, not at runtime.
# Default to the Docker-network URL (used by SSR rewrites); override via
# docker-compose build args for local dev where the browser needs localhost.
ARG NEXT_PUBLIC_API_URL=http://api:8000/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

COPY apps/web/ ./apps/web/
RUN pnpm --filter @convocaradar/web run build

# ── Stage 2: minimal runtime image ───────────────────────────────────────────
FROM node:22-slim AS runner

# Keep the standalone tree's relative depth (/srv/app two levels below the
# workspace root): pnpm's traced node_modules use symlinks like
# node_modules/next -> ../../../node_modules/.pnpm/<hash>/node_modules/next,
# which only resolve if the app sits exactly two directories below the
# directory holding the traced node_modules.
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user (uid/gid 1001 — matches Next.js defaults).
RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs --create-home --home-dir /home/nextjs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone/apps/web ./srv/app
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./srv/app/.next/static
# public/ is optional in this repo — skipped (not present).

WORKDIR /app/srv/app

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server.js"]
