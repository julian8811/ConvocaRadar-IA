# Contributor Setup — Local Development

This guide gets a new contributor from `git clone` to a working local
environment. Read it once end-to-end before you start.

## 1. Prerequisites

- **Python 3.12+** (`python3 --version`)
- **Node.js 22+** (Node 18 works for most scripts but Next.js requires 22)
- **pnpm** (`corepack enable && corepack prepare pnpm@10 --activate`)
- **Docker** (for Postgres + Redis via `docker-compose up`)
- **git** and the **GitHub CLI** (`brew install gh` / `apt install gh`)

## 2. Clone the repository

```bash
gh repo clone julian8811/ConvocaRadar-IA
cd ConvocaRadar-IA
```

## 3. Get a GitHub Personal Access Token (PAT)

You need a PAT to push branches and (if you are a maintainer) to trigger
deploys. The deploy workflow also uses it to comment on PRs.

1. Go to **GitHub → Settings → Developer settings → Personal access
   tokens → Fine-grained tokens** (or **Tokens (classic)** if you need
   `workflow` scope).
2. Click **Generate new token**.
3. Set the scopes you need:
   - **`repo`** — read/write to the repository (always required)
   - **`workflow`** — only if you will edit `.github/workflows/*.yml`
   - **`read:org`** — only if you will deploy to Render via the
     workflow and the repo is in an organization with SSO
4. **Expiration**: 90 days. Calendar a reminder; do not let it expire
   silently mid-task.
5. **Copy the token** — you will not see it again.

Authenticate `git` and the GitHub CLI with the token:

```bash
gh auth login --with-token  # paste the token
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

**Treat the PAT like a password.** Never commit it. Never paste it in a
chat. Never screenshot it. If it leaks, revoke it immediately (Settings
→ Developer settings → Personal access tokens → Revoke).

## 4. Set up local environment variables

```bash
# From the repo root
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local 2>/dev/null || true
```

Open `.env` and fill in:

- `DATABASE_URL` — leave `postgresql+psycopg://...` from `docker-compose.yml`
- `REDIS_URL` — leave `redis://localhost:6379/0` for local
- `JWT_SECRET` — generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
- `INTERNAL_API_KEY` — generate with the same command
- `SMTP_*` — leave blank unless you are testing email delivery
- `OPENAI_API_KEY` — leave blank to use the local heuristic provider

**Never commit `.env`.** It is already in `.gitignore` at the repo root
and at `apps/web/.gitignore`. If you ever see `.env` show up in
`git status`, **stop** and remove it from the index (`git rm --cached
.env`) before continuing.

## 5. Run the secret scanner before every commit

```bash
bash scripts/check-secrets.sh
```

The scanner greps the working tree for `ghp_`, `vcp_`, `sk-`, `pk_`,
and `rk_` patterns. It exits non-zero on any match and prints the
offending files.

To run it automatically on every commit:

```bash
ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The script skips `.git`, `node_modules`, `.venv`, `__pycache__`,
`dist`, `.next`, and other build artifacts. See the script header for
the full ignore list.

## 6. Bring up the backing services

```bash
docker-compose up -d          # Postgres + Redis + MinIO
cd apps/api && pnpm install   # if you have a top-level pnpm workspace
# OR
cd apps/api && pip install -e ".[dev]"
cd apps/web && pnpm install
```

## 7. Run the test suites

```bash
# API tests (62+ assertions)
cd apps/api && pytest -x

# Worker tests (84 assertions)
cd apps/worker && pytest -x

# Web tests + typecheck
cd apps/web && pnpm tsc --noEmit
cd apps/web && pnpm test
```

## 8. Open a pull request

```bash
git checkout -b feat/your-change
# ... make changes, commit with conventional commits ...
git push -u origin feat/your-change
gh pr create --base main --title "feat: your change" --body "..."
```

CI will run the test suites. Once green, request a review.

## 9. Where to get help

- **Setup issues**: ping `@julian8811` in the team chat
- **CI failures**: check `.github/workflows/` and the most recent run on
  the `Actions` tab
- **Security questions**: see `docs/security/secret-rotation.md` for
  rotation schedules; for an active incident, page `@julian8811`
  directly

Welcome aboard.
