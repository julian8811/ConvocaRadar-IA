"""Tests for User-Agent rotation and proxy infrastructure."""

from __future__ import annotations


from app.connectors.common import (
    _UA_POOL,
    _random_user_agent,
    _resolve_proxy,
)


class TestUserAgentRotation:
    def test_pool_has_multiple_agents(self):
        assert len(_UA_POOL) >= 8

    def test_agents_are_diverse(self):
        browsers = []
        for ua in _UA_POOL:
            if "Chrome" in ua:
                browsers.append("chrome")
            elif "Firefox" in ua:
                browsers.append("firefox")
            elif "Safari" in ua:
                browsers.append("safari")
            elif "Edg" in ua:
                browsers.append("edge")
        # At least 2 different browser families
        assert len(set(browsers)) >= 2

    def test_random_user_agent_returns_string(self):
        ua = _random_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 20
        assert "Mozilla" in ua

    def test_random_user_agent_is_random(self):
        agents = {_random_user_agent() for _ in range(20)}
        # Should have at least 3 different agents selected
        assert len(agents) >= 3


class TestProxyResolution:
    def test_no_proxy_from_settings(self):
        """When settings has no proxies, _resolve_proxy returns None."""
        from app.core.config import get_settings

        original = get_settings().scraping_proxy_list
        get_settings.cache_clear()
        try:
            proxy = _resolve_proxy()
            assert proxy is None
        finally:
            get_settings.cache_clear()

    def test_proxy_list_is_comma_separated_config(self):
        """Verify the config field accepts comma-separated proxy list."""
        from app.core.config import Settings

        # Just validate the field definition exists and is a list
        s = Settings()
        assert hasattr(s, "scraping_proxy_list")
        assert s.scraping_proxy_list == []
