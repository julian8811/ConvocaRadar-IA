"""Regression guards for opportunity deduplication tenant isolation."""

from __future__ import annotations

import ast
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
OPPORTUNITY_SERVICE = API_DIR / "app" / "services" / "opportunity.py"


def _create_opportunity_source() -> str:
    tree = ast.parse(OPPORTUNITY_SERVICE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "create_opportunity":
            return ast.unparse(node)
    raise AssertionError("create_opportunity() not found")


def test_every_create_opportunity_dedup_fallback_is_tenant_scoped() -> None:
    """The final slug/entity/date fallback must not match another tenant's row."""
    source = _create_opportunity_source()

    # create_opportunity has several dedup paths. The organization scope helper
    # must be present in the final slug/entity/close-date fallback too; otherwise
    # a matching row owned by another organization can be updated and returned.
    slug_fallback = source.rsplit("Opportunity.slug == slug", 1)[0]
    tail = slug_fallback[-500:]
    assert "_organization_opportunity_scope(organization_id)" in tail
