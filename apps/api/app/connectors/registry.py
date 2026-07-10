"""Connector registry — replaces the if-elif chain with a registration pattern.

Usage
-----
    from app.connectors.registry import register, get_connector

    @register("grants-gov")
    class GrantsGovConnector:
        ...

    # Later, anywhere in the codebase:
    conn = get_connector("grants-gov", "https://api.example.com")
"""

from __future__ import annotations

_connectors: dict[str, type] = {}


def register(key: str):
    """Decorator that registers a connector class under *key*.

    The class is stored in the internal registry and can later be retrieved
    via ``get_connector(key, ...)``.  The decorator returns the class
    unchanged (identity preserved).
    """

    def decorator(cls):
        _connectors[key] = cls
        return cls

    return decorator


def get_connector(key: str, base_url: str | None = None, **kwargs):
    """Return an instance of the connector registered for *key*.

    Parameters
    ----------
    key : str
        The registration key (e.g. ``"grants-gov"``).
    base_url : str or None
        Optional base URL forwarded to the connector constructor.
    **kwargs
        Additional keyword arguments forwarded to the connector constructor.

    Returns
    -------
    connector
        An instance of the registered class, constructed as
        ``cls(base_url, **kwargs)``.

    Raises
    ------
    KeyError
        If no connector is registered under *key*.
    """
    cls = _connectors.get(key)
    if cls is None:
        raise KeyError(f"No connector registered for key: {key}")
    return cls(base_url, **kwargs)


def registered_keys() -> list[str]:
    """Return a copy of the current registration keys."""
    return list(_connectors.keys())
