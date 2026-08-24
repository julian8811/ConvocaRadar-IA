"""Tests for source maintenance: cleanup, retry, country fix."""

from __future__ import annotations




def test_country_inference_fixes_sin_dato():
    """infer_country_from_entity should fix 'Sin dato' countries."""
    from app.connectors.common import infer_country_from_entity
    # Known entities
    assert infer_country_from_entity("CONICET Argentina", None) == "Argentina"
    assert infer_country_from_entity("FAPESP Brasil", None) == "Brazil"
    # Domain-based
    assert infer_country_from_entity("Entity", "www.findeter.gov.co") == "Colombia"
    assert infer_country_from_entity("Entity", "www.fapesp.br") == "Brazil"
    # Unknown should return "Por validar"
    assert infer_country_from_entity("Unknown Org", None) == "Por validar"


class TestRetryLogic:
    def test_fetch_httpx_text_has_retry(self):
        """fetch_httpx_text should accept retries parameter."""
        import inspect
        from app.connectors.common import fetch_httpx_text
        sig = inspect.signature(fetch_httpx_text)
        assert "retries" in sig.parameters
        assert sig.parameters["retries"].default == 2
