# syntax=docker/dockerfile:1.7
# ── Stage 1: install deps ────────────────────────────────────────────────────
FROM node:22-slim AS deps

WORKDIR /app

# Install only the production deps first for better layer caching.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --ignore-scripts

# ── Stage 2: build the Next.js app ───────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# NEXT_PUBLIC_* vars are embedded at build time by Next.js, not at runtime.
# Default to the Docker-network URL (used by SSR rewrites); override via
# docker-compose build args for local dev where the browser needs localhost.
ARG NEXT_PUBLIC_API_URL=http://api:8000/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
RUN npm run build

# ── Stage 3: minimal runtime image ───────────────────────────────────────────
FROM node:22-slim AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user (uid/gid 1001 — matches Next.js defaults).
RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs --create-home --home-dir /home/nextjs nextjs

# Standalone output nests at standalone/app/ because of the monorepo workspace
# layout (WORKDIR=/app, app source at ./apps/web copied to /app).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone/app ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# public/ is optional in this repo — skipped (not present).

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server.js"]
