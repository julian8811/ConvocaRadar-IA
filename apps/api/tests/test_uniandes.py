"""Tests for the Uniandes seed data fix.

Verifies that the ``uniandes-investigacion`` source definition in
``app/db/seed.py`` has the corrected ``base_url`` and ``allowed_domains``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.db.seed import seed_default_sources


class TestUniandesSeedDefinition:
    """Verify the uniandes-investigacion source definition in seed.py."""

    def _find_uniandes_source(self, db_mock):
        """Extract the Source that matches uniandes-investigacion from db.add calls."""
        for call_args in db_mock.add.call_args_list:
            source = call_args[0][0]
            if getattr(source, "key", None) == "uniandes-investigacion":
                return source
        return None

    @pytest.fixture
    def db(self):
        mock_db = MagicMock()
        mock_db.scalar.return_value = None
        return mock_db

    @pytest.fixture
    def org(self):
        org = MagicMock()
        org.id = 42
        return org

    def test_uniandes_base_url_is_updated(self, db, org):
        """The base_url should point to the new investigacioncreacion path."""
        seed_default_sources(db, org, bootstrap_mode=True)

        uniandes = self._find_uniandes_source(db)
        assert uniandes is not None, "uniandes-investigacion source was not created"

        assert uniandes.base_url == "https://www.uniandes.edu.co/investigacioncreacion/", (
            f"Expected updated base_url, got: {uniandes.base_url}"
        )

    def test_uniandes_allowed_domains_includes_both(self, db, org):
        """allowed_domains should include both uniandes.edu.co and www.uniandes.edu.co."""
        seed_default_sources(db, org, bootstrap_mode=True)

        uniandes = self._find_uniandes_source(db)
        assert uniandes is not None, "uniandes-investigacion source was not created"

        domains = uniandes.allowed_domains
        assert "uniandes.edu.co" in domains, (
            f"Expected 'uniandes.edu.co' in allowed_domains, got: {domains}"
        )
        assert "www.uniandes.edu.co" in domains, (
            f"Expected 'www.uniandes.edu.co' in allowed_domains, got: {domains}"
        )

    def test_findeter_source_type_is_api(self, db, org):
        """The findeter-convocatorias source_type should be 'api' (XML sitemap)."""
        seed_default_sources(db, org, bootstrap_mode=True)

        # Grab the findeter source from db.add calls
        findeter = None
        for call_args in db.add.call_args_list:
            source = call_args[0][0]
            if getattr(source, "key", None) == "findeter-convocatorias":
                findeter = source
                break

        assert findeter is not None, "findeter-convocatorias source was not created"
        assert findeter.source_type == "api", (
            f"Expected source_type='api', got: {findeter.source_type}"
        )
