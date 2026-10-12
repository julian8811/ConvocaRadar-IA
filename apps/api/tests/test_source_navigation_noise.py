"""Regression tests: avoid source-specific navigation false positives."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_script_path = Path(__file__).resolve().parents[1] / "app" / "services" / "source_quality.py"
_spec = spec_from_file_location("source_quality_under_test", _script_path)
_quality = module_from_spec(_spec)
_spec.loader.exec_module(_quality)
reason = _quality.source_non_opportunity_reason


def test_cost_informational_navigation_is_rejected():
    assert reason("cost-open-calls", "Who is who", "https://www.cost.eu/about/who-is-who/") is not None
    assert reason("cost-open-calls", "Timeline", "https://www.cost.eu/about/timeline/") is not None


def test_real_cost_funding_page_is_not_rejected():
    assert reason(
        "cost-open-calls", "Open Call", "https://www.cost.eu/funding/open-call-a-simple-one-step-application-process/"
    ) is None


def test_adaptation_sector_category_not_funding_call():
    assert reason(
        "adaptation-fund-apply",
        "Urban Development",
        "https://www.adaptation-fund.org/projects-programmes/project-sectors/urban-development/",
    ) is not None


def test_adaptation_application_page_is_preserved():
    assert reason(
        "adaptation-fund-apply", "Apply for Funding", "https://www.adaptation-fund.org/apply-funding/"
    ) is None


def test_same_url_with_other_source_key_is_not_filtered():
    assert reason(
        "some-other-source", "Urban Development",
        "https://www.adaptation-fund.org/projects-programmes/project-sectors/urban-development/"
    ) is None


def test_lookalike_host_is_not_filtered():
    assert reason(
        "cost-open-calls", "Who is who", "https://fake-cost.eu/about/who-is-who/"
    ) is None


def test_missing_or_unexpected_urls_are_handled_by_normal_validation():
    assert reason("cost-open-calls", "Who is who", None) is None
    assert reason("cost-open-calls", "Who is who", "ftp://cost.eu/about/who-is-who") is None


def test_news_and_historical_procurement_not_broadly_auto_rejected():
    assert reason("idt-noticias", "Some article", "https://www.idt.gov.co/noticias/story") is None
    assert reason("findeter-convocatorias", "PAF 2023", "https://www.findeter.gov.co/convocatorias/paf-2023") is None


def test_malformed_url_does_not_abort_scraping():
    assert reason("cost-open-calls", "Navigation", "http://[malformed") is None
