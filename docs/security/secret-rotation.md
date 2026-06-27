# Secret Rotation Guide

ConvocaRadar IA handles funding opportunities for Latin-American research
and innovation teams. The application integrates with several third-party
services, and any leaked credential is a real-world security incident —
not a theoretical one. This document defines **where secrets live**, **how
to rotate them**, and **what to do if one leaks**.

## TL;DR

- **Never put a secret in chat, screenshots, or commits.** Use GitHub Actions Secrets (Settings → Secrets and variables → Actions).
- **Rotate production secrets every 90 days** (or immediately on any
  suspected exposure).
- **Run `bash scripts/check-secrets.sh` before every commit.** The script
  catches `ghp_`, `vcp_`, `sk-`, `pk_`, and `rk_` patterns.

---

## 1. Where secrets live

| Surface                  | How to set the secret                                  | Scope                |
| ------------------------ | ------------------------------------------------------ | -------------------- |
| Render (API + Worker)    | Render dashboard → Service → Environment → Secret      | Production secrets   |
| Vercel (Web)             | Vercel dashboard → Project → Settings → Env Variables  | Frontend env         |
| GitHub Actions           | Repo → Settings → Secrets and variables → Actions      | CI/CD tokens         |
| Local dev                | Copy `.env.example` to `.env`, fill in real values     | Never commit `.env`  |

The full list of env vars lives in `apps/api/app/core/config.py` (Pydantic
Settings) and `apps/web/.env.example`.

## 2. Rotation schedule

| Secret                                | Frequency           | Owner              | Procedure                                                                                         |
| ------------------------------------- | ------------------- | ------------------ | ------------------------------------------------------------------------------------------------- |
| `JWT_SECRET`                          | Every 90 days       | Backend maintainer | Render → API service → Environment → rotate. Invalidate all sessions (users re-login).           |
| `INTERNAL_API_KEY`                    | Every 90 days       | Backend maintainer | Render → API + Worker services. Restart both after rotation.                                       |
| `SENTRY_DSN`                          | Every 90 days       | Backend maintainer | Sentry → Settings → Auth Tokens. Create new project key, replace DSN, redeploy.                   |
| `OPENAI_API_KEY` / `LLM_API_KEY`      | Every 90 days       | Backend maintainer | OpenAI dashboard → API keys → Revoke + Create. Set usage limits.                                  |
| `S3_*` (R2 / MinIO)                   | Every 180 days      | Backend maintainer | R2 → Manage R2 API Tokens → Rotate.                                                                |
| `SMTP_PASSWORD`                       | Every 90 days       | Backend maintainer | SMTP provider console. Update Render env, redeploy API.                                            |
| GitHub PATs used by maintainers       | Every 90 days       | Each maintainer    | GitHub → Settings → Developer settings → PATs → Regenerate. Update local `gh auth login`.          |
| Render API key (in GitHub Actions)    | Every 90 days       | Repo admin         | Render → Account Settings → API Keys → Rotate. Update GitHub Secret `RENDER_API_KEY`.             |
| Vercel deploy tokens                  | Every 90 days       | Frontend maintainer| Vercel → Account Settings → Tokens → Rotate. Update GitHub Secret `VERCEL_TOKEN`.                 |

The 90-day cadence matches GitHub's recommendation for PATs and is a
sensible default for cloud credentials. If a secret has higher blast
radius (e.g. production database, payment processor), shorten the
rotation window.

## 3. Rotation procedure (worked example)

Rotating the Render API key used by the deploy workflow:

1. **Generate the new key**:
   - Render dashboard → Account Settings → API Keys → Create API Key
   - Name: `github-actions-deploy-2026-Q3`
2. **Update GitHub**:
   - Repo → Settings → Secrets and variables → Actions
   - Edit `RENDER_API_KEY` → paste the new value
3. **Revoke the old key**:
   - Same dashboard → click the old key → Revoke
4. **Verify the next deploy works**:
   - Trigger a manual `workflow_dispatch` of `.github/workflows/deploy.yml`
   - Watch the `render-api` job — it should pass with the new key
5. **Record the rotation** in your team's secret-rotation log (date,
   secret, who, ticket/PR).

## 4. What to do if a secret leaks

Assume the credential is **public the moment it touches Git history, a
chat, or a screenshot**, even if you "deleted it right after".

1. **Rotate immediately** — do not wait. The leaked value is in the hands
   of anyone with the URL or the chat log.
2. **Remove from history** if it was committed:
   - `git filter-repo --invert-paths --path apps/api/app/leaked.py` (or
     `--blob-callback`)
   - Force-push and ask collaborators to re-clone
   - BFG Repo-Cleaner is an alternative: `bfg --delete-files leaked.py`
3. **Audit access logs** for the credential's service. Look for unknown
   IPs, unusual times, new API calls.
4. **Open an incident** with the team. Track it in your issue tracker.
5. **Add a guard** so it cannot happen again:
   - Add the path to `.gitignore`
   - Extend `scripts/check-secrets.sh` if the pattern was new
   - Wire the script into a pre-commit hook (see below)

## 5. Pre-commit hook (recommended)

To make the secret scanner run automatically before every commit:

```bash
# From the repo root
ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook runs `bash scripts/check-secrets.sh` and aborts the commit if
the exit code is non-zero. This is belt-and-suspenders alongside the
GitHub Actions secret-scan job.

## 6. The secret-rotation log

Maintain a simple log in your team's workspace:

```markdown
## 2026-09-15 — JWT_SECRET
- Owner: Julian
- New value: <redacted — stored in Render>
- Old value revoked: yes
- Users impacted: all (forced re-login)
- Ticket: OPS-417
```

This log is internal — never paste the actual secret value.
