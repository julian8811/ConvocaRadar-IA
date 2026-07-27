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

# Standalone output already includes a minimal node_modules with only what the
# app imports. We still need to ship the static assets that live outside the
# standalone bundle (.next/static).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# public/ is optional in this repo; copy only if it exists at build time.
COPY --from=builder /app/public ./public 2>/dev/null || true

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server.js"]
