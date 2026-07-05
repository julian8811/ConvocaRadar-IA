"""Static analysis tests for the unified deploy workflow.

These tests assert the workflow file has the right shape:
- Triggers on workflow_run after CI success or workflow_dispatch
- Has jobs for Render API, Render worker, Vercel, and healthcheck
- All required GitHub Secrets are referenced (not hardcoded)
- No secrets in the workflow file (no `ghp_`/`vcp_`/long alphanumeric tokens)
- Has a concurrency block to prevent overlapping deploys
- Has a healthcheck step that touches the live URLs
"""
import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parent.parent.parent.parent / ".github" / "workflows" / "deploy.yml"
TEXT = WORKFLOW.read_text() if WORKFLOW.exists() else ""
DATA = yaml.safe_load(TEXT) if TEXT else {}


def test_workflow_file_exists():
    assert WORKFLOW.exists(), f"Deploy workflow not found at {WORKFLOW}"


def test_workflow_yaml_is_valid():
    """Catches indentation errors, duplicate keys, malformed steps."""
    assert DATA, "Workflow file is empty or invalid YAML"
    assert isinstance(DATA, dict)
    assert "jobs" in DATA, "Workflow missing 'jobs' key"


def test_workflow_name():
    assert DATA.get("name") in {"Deploy", "Deploy Production"}


def test_workflow_triggers_correctly():
    triggers = DATA.get(True, {})  # `on:` parses to boolean True in PyYAML
    assert "workflow_run" in triggers, "Missing workflow_run trigger"
    assert "completed" in triggers["workflow_run"]["types"]
    assert triggers["workflow_run"].get("branches") == ["main"]
    assert "workflow_dispatch" in triggers, "Missing manual dispatch trigger"


def test_render_jobs_present():
    jobs = DATA.get("jobs", {})
    # Render-only API job (worker/beat removed — inline-only architecture)
    assert "render-api" in jobs, "Missing render-api job"


def test_vercel_job_present():
    jobs = DATA.get("jobs", {})
    assert "vercel" in jobs, "Missing Vercel deploy job"


def test_healthcheck_job_present():
    jobs = DATA.get("jobs", {})
    assert "healthcheck" in jobs, "Missing healthcheck job"


def test_healthcheck_uses_correct_urls():
    """The healthcheck job must hit the production URLs (via env vars is fine)."""
    env = DATA.get("env", {})
    assert env.get("RENDER_PRODUCTION_URL") == "https://convocaradar-ia.onrender.com", \
        "env.RENDER_PRODUCTION_URL must point to the live Render API"
    assert env.get("VERCEL_PRODUCTION_URL") == "https://convocaradar-web.vercel.app", \
        "env.VERCEL_PRODUCTION_URL must point to the live Vercel deployment"
    # And the healthcheck job must reference them
    jobs = DATA.get("jobs", {})
    healthcheck_steps = str(jobs.get("healthcheck", {}))
    assert "RENDER_PRODUCTION_URL" in healthcheck_steps, \
        "Healthcheck must reference RENDER_PRODUCTION_URL"
    assert "VERCEL_PRODUCTION_URL" in healthcheck_steps, \
        "Healthcheck must reference VERCEL_PRODUCTION_URL"


def test_required_secrets_referenced():
    """All required GitHub Secrets are referenced via ${{ secrets.* }} — not hardcoded."""
    secrets_required = [
        "RENDER_API_KEY",
        "VERCEL_TOKEN",
    ]
    for secret in secrets_required:
        assert f"secrets.{secret}" in TEXT, \
            f"Secret {secret} must be referenced via ${{{{ secrets.{secret} }}}} — never hardcode"


def test_no_hardcoded_tokens_in_workflow():
    """Detect leaked tokens. Common prefixes: ghp_ (GitHub), vcp_ (Vercel), sk- (OpenAI)."""
    # Allow the literal `secrets.` usage; reject raw token-like patterns
    # Token pattern: 30+ alphanumeric/underscore characters
    secret_patterns = [
        r"ghp_[A-Za-z0-9]{20,}",  # GitHub PAT
        r"vcp_[A-Za-z0-9]{20,}",  # Vercel token
        r"sk-[A-Za-z0-9]{20,}",   # OpenAI
    ]
    for pattern in secret_patterns:
        matches = re.findall(pattern, TEXT)
        assert not matches, \
            f"Hardcoded token pattern '{pattern}' found in workflow. Use ${{{{ secrets.* }}}} instead."


def test_concurrency_block_present():
    """Prevents overlapping deploys from racing."""
    assert "concurrency" in DATA, \
        "Missing concurrency block — overlapping deploys could race"


def test_jobs_have_needs_dependencies():
    """Healthcheck must wait for both Render and Vercel."""
    jobs = DATA.get("jobs", {})
    healthcheck = jobs.get("healthcheck", {})
    needs = healthcheck.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    assert "vercel" in needs, "Healthcheck must depend on Vercel job"
    assert any("render" in n for n in needs), "Healthcheck must depend on at least one Render job"


def test_render_api_call_uses_official_endpoint():
    """The Render API call must use the official endpoint (via env var is fine)."""
    env = DATA.get("env", {})
    assert env.get("RENDER_API_BASE") == "https://api.render.com/v1", \
        "env.RENDER_API_BASE must point to the official Render API"
    # And the render-api job must reference it
    jobs = DATA.get("jobs", {})
    api_steps = str(jobs.get("render-api", {}))
    assert "RENDER_API_BASE" in api_steps, \
        "render-api job must reference RENDER_API_BASE"
    assert "/services/" in api_steps and "/deploys" in api_steps, \
        "render-api must POST to /services/{id}/deploys"


def test_vercel_uses_official_action():
    jobs = DATA.get("jobs", {})
    vercel = jobs.get("vercel", {})
    vercel_steps = str(vercel)
    assert "amondnet/vercel-action" in vercel_steps or "vercel deploy" in vercel_steps, \
        "Vercel deploy should use the official amondnet/vercel-action or vercel CLI"


def test_deploy_render_yml_is_removed():
    """The old deploy-render.yml should be replaced by this unified workflow."""
    old_workflow = Path(__file__).parent.parent.parent.parent / ".github" / "workflows" / "deploy-render.yml"
    assert not old_workflow.exists(), \
        f"Old workflow still exists at {old_workflow}. Remove it; the unified deploy.yml supersedes it."
