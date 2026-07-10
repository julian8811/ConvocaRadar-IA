"""Tests for the connector registry pattern."""
from __future__ import annotations

import pytest

from app.connectors.registry import get_connector, register, registered_keys


# ── Helper: connector stub that accepts registry-style constructor ────────


def _make_connector_cls():
    """Return a plain class whose ``__init__`` matches the registry contract
    ``(base_url, **kwargs)`` so tests don't leak ``TypeError``."""

    class _Stub:
        def __init__(self, base_url: str | None = None, **kwargs):
            self.base_url = base_url
            self.kwargs = kwargs

    return _Stub


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear the registry before each test so state does not leak.

    We reach into the module's private dict so the public API is exercised
    naturally in each test body.
    """
    import app.connectors.registry as regmod

    saved = dict(regmod._connectors)
    regmod._connectors.clear()
    yield
    regmod._connectors.clear()
    regmod._connectors.update(saved)


# ── register / get_connector ──────────────────────────────────────────────


class TestRegisterAndGet:
    """Happy path: a registered connector can be retrieved by key."""

    def test_register_then_get_returns_instance(self):
        Stub = _make_connector_cls()
        register("test-alpha")(Stub)

        instance = get_connector("test-alpha", "http://alpha.dev")
        assert isinstance(instance, Stub)
        assert instance.base_url == "http://alpha.dev"

    def test_register_returns_the_class(self):
        """The decorator must return the class unchanged (identity)."""

        class BetaConnector:
            pass

        decorated = register("test-beta")(BetaConnector)
        assert decorated is BetaConnector

    def test_multiple_keys(self):
        Stub = _make_connector_cls()
        register("key-a")(Stub)

        OtherStub = _make_connector_cls()
        register("key-b")(OtherStub)

        assert isinstance(get_connector("key-a"), Stub)
        assert isinstance(get_connector("key-b"), OtherStub)

    def test_registered_keys_returns_current_keys(self):
        Stub = _make_connector_cls()
        register("key-c")(Stub)

        assert "key-c" in registered_keys()

    def test_registered_keys_returns_a_copy(self):
        keys_before = registered_keys()
        Stub = _make_connector_cls()
        register("key-d")(Stub)

        keys_after = registered_keys()
        assert "key-d" in keys_after
        # The list returned earlier is not mutated
        assert "key-d" not in keys_before

    def test_kwargs_forwarded_to_connector(self):
        Stub = _make_connector_cls()
        register("key-kwargs")(Stub)

        instance = get_connector("key-kwargs", "http://example.com", foo="bar", count=42)
        assert instance.kwargs == {"foo": "bar", "count": 42}

    def test_base_url_none_by_default(self):
        Stub = _make_connector_cls()
        register("key-none")(Stub)

        instance = get_connector("key-none")
        assert instance.base_url is None


# ── Error cases ──────────────────────────────────────────────────────────


class TestRegistryErrors:
    """Missing keys and type mismatches."""

    def test_get_missing_key_raises_key_error(self):
        with pytest.raises(KeyError, match="No connector registered for key: nonexistent"):
            get_connector("nonexistent")

    def test_get_missing_key_error_message_includes_key(self):
        unknown = "this-key-does-not-exist"
        with pytest.raises(KeyError) as exc:
            get_connector(unknown)
        assert unknown in str(exc.value)

    def test_last_registration_wins(self):
        First = _make_connector_cls()
        First.label = "first"  # type: ignore[attr-defined]
        register("collision")(First)

        Second = _make_connector_cls()
        Second.label = "second"  # type: ignore[attr-defined]
        register("collision")(Second)

        instance = get_connector("collision")
        assert isinstance(instance, Second)

    def test_register_empty_key(self):
        """An empty string key is technically allowed but useless."""
        Stub = _make_connector_cls()
        register("")(Stub)

        assert "" in registered_keys()
        assert isinstance(get_connector(""), Stub)


# ── Integration: factory routes through registry ─────────────────────────


class TestFactoryUsesRegistry:
    """factory.connector_for() must prefer registry over if-elif chain."""

    def test_registered_key_routes_through_registry(self):
        """A freshly registered key is used by connector_for()."""
        from app.connectors.factory import connector_for

        Stub = _make_connector_cls()
        register("test-factory-alpha")(Stub)

        instance = connector_for("test-factory-alpha", "http://factory.dev")
        assert isinstance(instance, Stub)
        assert instance.base_url == "http://factory.dev"

    def test_registered_key_overrides_if_elif(self):
        """Even if a key exists in the if-elif chain, a newer
        registration in the registry takes precedence."""
        from app.connectors.factory import connector_for
        from app.connectors.nsf import NSFFundingConnector

        Stub = _make_connector_cls()
        register("nsf-funding")(Stub)

        instance = connector_for("nsf-funding", "http://override.test")
        assert isinstance(instance, Stub)
        assert not isinstance(instance, NSFFundingConnector)

    def test_registered_connector_does_not_receive_factory_extras(self):
        """Factory-only kwargs (entity_name, default_country, etc.) are
        NOT forwarded to registered connectors — those params are only
        meaningful for the GenericHtmlConnector fallback."""
        from app.connectors.factory import connector_for

        Stub = _make_connector_cls()
        register("test-factory-gamma")(Stub)

        # These extra kwargs should NOT cause a TypeError and should
        # NOT leak into the connector's kwargs.
        instance = connector_for(
            "test-factory-gamma",
            "http://factory.dev",
            entity_name="ShouldNotLeak",
            default_country="XX",
        )
        assert isinstance(instance, Stub)
        assert instance.kwargs == {}  # factory does NOT forward extras


# ── Fallback: unregistered keys still work ───────────────────────────────


class TestFactoryFallback:
    """Keys NOT in the registry must fall through to the if-elif chain."""

    def test_unregistered_key_falls_back_to_source_type(self):
        from app.connectors.factory import connector_for
        from app.connectors.manual import ManualConnector

        instance = connector_for("nobody-registered-this", "http://example.com", source_type="manual")
        assert isinstance(instance, ManualConnector)

    def test_unregistered_key_falls_back_to_rss(self):
        from app.connectors.factory import connector_for
        from app.connectors.rss import RssConnector

        instance = connector_for("some-custom-rss", "http://example.com/feed.xml", source_type="rss")
        assert isinstance(instance, RssConnector)

    def test_unregistered_key_defaults_to_generic_html(self):
        from app.connectors.factory import connector_for
        from app.connectors.generic_html import GenericHtmlConnector

        instance = connector_for("completely-unknown", "http://example.com")
        assert isinstance(instance, GenericHtmlConnector)

    def test_existing_if_elif_keys_still_work(self):
        """Keys like 'nsf-funding' that are NOT being migrated yet
        must still resolve through the if-elif chain."""
        from app.connectors.factory import connector_for
        from app.connectors.nsf import NSFFundingConnector

        instance = connector_for("nsf-funding", "http://nsf.gov")
        assert isinstance(instance, NSFFundingConnector)
