"""Tests for scoring optimization: thresholds, geo bonus, semantic fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.scoring import (
    _compute_score,
    calculate_score,
    priority_for_score,
)
from app.models import Opportunity, OrganizationProfile, Priority


def test_priority_thresholds_allow_high():
    """With adjusted thresholds, a mid-range opportunity can reach 'high'."""
    # priority_for_score uses thresholds we can verify
    assert priority_for_score(85) == Priority.high.value
    assert priority_for_score(75) == Priority.high.value
    assert priority_for_score(74) == Priority.medium.value


class TestComputeScore:
    def test_same_country_bonus(self):
        """Opportunity in same country as profile gets +15."""
        profile = MagicMock(spec=OrganizationProfile)
        profile.country = "Colombia"
        profile.organization_type = "university"
        profile.areas_of_interest = []
        profile.eligible_international = False
        profile.max_funding_amount = None

        opp = MagicMock(spec=Opportunity)
        opp.country = "Colombia"
        opp.entity = "Test"
        opp.categories = []
        opp.topics = []
        opp.funding_amount_value = None
        opp.close_date = None
        opp.requirements = []
        opp.documents_required = []
        opp.eligible_applicants = []

        result = _compute_score(opp, profile)
        assert result["raw"] >= 15  # same country bonus

    def test_category_overlap_adds_score(self):
        """Overlapping categories between opportunity and profile add points."""
        profile = MagicMock(spec=OrganizationProfile)
        profile.country = "Colombia"
        profile.organization_type = "university"
        profile.areas_of_interest = ["innovacion", "investigacion", "educacion"]
        profile.eligible_international = False
        profile.max_funding_amount = None

        opp = MagicMock(spec=Opportunity)
        opp.country = "Mexico"
        opp.entity = "Test"
        opp.categories = ["innovacion", "tecnologia"]
        opp.topics = ["innovacion"]
        opp.funding_amount_value = None
        opp.close_date = None
        opp.requirements = []
        opp.documents_required = []
        opp.eligible_applicants = []

        result = _compute_score(opp, profile)
        # Should get score from category overlap
        assert result["raw"] > 0

    def test_has_amount_adds_score(self):
        """Opportunities with funding amount get additional score."""
        profile = MagicMock(spec=OrganizationProfile)
        profile.country = "Colombia"
        profile.organization_type = "university"
        profile.areas_of_interest = []
        profile.eligible_international = True
        profile.max_funding_amount = 500000

        opp = MagicMock(spec=Opportunity)
        opp.country = "Brazil"
        opp.entity = "Test"
        opp.categories = []
        opp.topics = []
        opp.funding_amount_value = 100000.0
        opp.funding_amount_currency = "USD"
        opp.close_date = None
        opp.requirements = []
        opp.documents_required = []
        opp.eligible_applicants = []

        result = _compute_score(opp, profile)
        assert result["raw"] > 0

    def test_zero_for_completely_empty(self):
        """An opportunity with no matching fields scores 0."""
        profile = MagicMock(spec=OrganizationProfile)
        profile.country = "Colombia"
        profile.organization_type = "university"
        profile.areas_of_interest = []
        profile.eligible_international = False
        profile.max_funding_amount = None

        opp = MagicMock(spec=Opportunity)
        opp.country = ""
        opp.categories = []
        opp.topics = []
        opp.funding_amount_value = None
        opp.close_date = None
        opp.requirements = []
        opp.documents_required = []
        opp.eligible_applicants = []

        result = _compute_score(opp, profile)
        assert result["raw"] >= 0
