"""Tests for DomainBudgetManager — per-domain token bucket rate limiter.

TDD Cycle: tests written FIRST, then implementation.
"""
from __future__ import annotations

import threading
import time

from app.scraper.domain_budget import DomainBudgetManager


# ---------------------------------------------------------------------------
# Budget lookup and configuration
# ---------------------------------------------------------------------------


def test_budget_grants_gov_gets_three_slots() -> None:
    """grants.gov should have max_concurrent=3 (above the default of 2)."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://grants.gov/opportunity/1") is True
    assert manager.acquire("https://grants.gov/opportunity/2") is True
    assert manager.acquire("https://grants.gov/opportunity/3") is True
    assert manager.acquire("https://grants.gov/opportunity/4") is False


def test_budget_beta_grants_gov_gets_three_slots() -> None:
    """beta.grants.gov should also have max_concurrent=3."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://beta.grants.gov/opp/1") is True
    assert manager.acquire("https://beta.grants.gov/opp/2") is True
    assert manager.acquire("https://beta.grants.gov/opp/3") is True
    assert manager.acquire("https://beta.grants.gov/opp/4") is False


def test_budget_minciencias_gets_one_slot() -> None:
    """minciencias.gov.co should have max_concurrent=1."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://minciencias.gov.co/convocatoria/1") is True
    assert manager.acquire("https://minciencias.gov.co/convocatoria/2") is False


def test_budget_innpulsa_gets_one_slot() -> None:
    """innpulsacolombia.com should have max_concurrent=1."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://innpulsacolombia.com/programa/1") is True
    assert manager.acquire("https://innpulsacolombia.com/programa/2") is False


# ---------------------------------------------------------------------------
# Unknown domains get the default budget
# ---------------------------------------------------------------------------


def test_unknown_domain_defaults_to_two_slots() -> None:
    """Domains not in DEFAULTS should get max_concurrent=2."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://example.gov/opp/1") is True
    assert manager.acquire("https://example.gov/opp/2") is True
    assert manager.acquire("https://example.gov/opp/3") is False


def test_unknown_domain_two_slots_release_one() -> None:
    """Releasing one slot on an unknown domain should allow a new acquisition."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://other-source.org/a") is True
    assert manager.acquire("https://other-source.org/b") is True
    assert manager.acquire("https://other-source.org/c") is False
    manager.release("https://other-source.org/a")
    assert manager.acquire("https://other-source.org/c") is True


# ---------------------------------------------------------------------------
# Release resets budget
# ---------------------------------------------------------------------------


def test_release_resets_budget() -> None:
    """After release(), a slot should be freed for the same domain."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://minciencias.gov.co/a") is True
    assert manager.acquire("https://minciencias.gov.co/b") is False  # exhausted
    manager.release("https://minciencias.gov.co/a")
    assert manager.acquire("https://minciencias.gov.co/c") is True


def test_release_nonexistent_is_safe() -> None:
    """Calling release() for a domain with no acquired slots must not raise."""
    manager = DomainBudgetManager()
    manager.release("https://grants.gov/never-acquired")
    # No exception means success


# ---------------------------------------------------------------------------
# Delay calculation
# ---------------------------------------------------------------------------


def test_delay_for_returns_zero_when_no_delay_configured() -> None:
    """delay_for() should return 0.0 for domains with delay_seconds=0."""
    manager = DomainBudgetManager()
    assert manager.delay_for("https://grants.gov/opp/1") == 0.0


def test_delay_for_returns_zero_on_first_call() -> None:
    """delay_for() should return 0.0 when no prior request was made."""
    manager = DomainBudgetManager()
    # minciencias has delay_seconds=2, but no prior request
    assert manager.delay_for("https://minciencias.gov.co/a") == 0.0


def test_delay_after_request() -> None:
    """After acquire(), delay_for() should reflect the remaining delay time."""
    manager = DomainBudgetManager()
    manager.acquire("https://minciencias.gov.co/a")
    manager.release("https://minciencias.gov.co/a")
    # Immediately after, the delay window has barely elapsed
    remaining = manager.delay_for("https://minciencias.gov.co/b")
    assert remaining > 0.5, (
        f"Expected a positive delay after a minciencias request with "
        f"delay_seconds=2, got {remaining}"
    )


def test_delay_after_elapsed() -> None:
    """After the delay window passes, delay_for() should return 0.0."""
    import time as tm

    manager = DomainBudgetManager()
    manager.acquire("https://minciencias.gov.co/a")
    manager.release("https://minciencias.gov.co/a")
    # Wait for the delay window to elapse
    tm.sleep(2.1)
    remaining = manager.delay_for("https://minciencias.gov.co/b")
    assert remaining == 0.0, (
        f"Expected delay to be 0 after sleeping 2.1s (delay_seconds=2), "
        f"got {remaining}"
    )


# ---------------------------------------------------------------------------
# Playwright pattern: *playwright* glob
# ---------------------------------------------------------------------------


def test_playwright_glob_matches_url_containing_playwright() -> None:
    """URLs whose domain contains 'playwright' should get max_concurrent=1."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://playwright.internal/page") is True
    assert manager.acquire("https://playwright.internal/page2") is False


def test_playwright_glob_release() -> None:
    """Releasing a Playwright slot should allow a new acquisition."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://my-playwright-service.test/a") is True
    assert manager.acquire("https://my-playwright-service.test/b") is False
    manager.release("https://my-playwright-service.test/a")
    assert manager.acquire("https://my-playwright-service.test/c") is True


# ---------------------------------------------------------------------------
# Domain independence
# ---------------------------------------------------------------------------


def test_domains_are_independent() -> None:
    """Exhausting one domain's budget must not affect other domains."""
    manager = DomainBudgetManager()

    # Exhaust grants.gov (3 slots)
    assert manager.acquire("https://grants.gov/a") is True
    assert manager.acquire("https://grants.gov/b") is True
    assert manager.acquire("https://grants.gov/c") is True
    assert manager.acquire("https://grants.gov/d") is False

    # innpulsacolombia.com should still be available
    assert manager.acquire("https://innpulsacolombia.com/test") is True


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_thread_safety() -> None:
    """Concurrent acquire() calls on the same domain must not exceed max_concurrent.

    Uses threading.Barrier to maximize race conditions, mirroring the
    existing SlidingWindowLimiter thread-safety test pattern.
    """
    import concurrent.futures

    manager = DomainBudgetManager()
    n_threads = 20

    barrier = threading.Barrier(n_threads)

    def hit() -> bool:
        barrier.wait()
        return manager.acquire("https://example.com/same-resource")

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as ex:
        results = list(ex.map(lambda _: hit(), range(n_threads)))

    allowed = sum(1 for r in results if r is True)
    blocked = sum(1 for r in results if r is False)

    assert allowed == 2, (
        f"Thread-safety violation: {allowed} of {n_threads} concurrent "
        f"requests acquired slots (max default=2). Expected exactly 2."
    )
    assert blocked == n_threads - 2, (
        f"Expected {n_threads - 2} blocked, got {blocked}."
    )


# ---------------------------------------------------------------------------
# URL parsing edge cases
# ---------------------------------------------------------------------------


def test_url_with_port() -> None:
    """URLs with explicit ports should still match their domain config."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://grants.gov:8080/opp/1") is True
    assert manager.acquire("https://grants.gov:8080/opp/2") is True
    assert manager.acquire("https://grants.gov:8080/opp/3") is True
    assert manager.acquire("https://grants.gov:8080/opp/4") is False


def test_url_with_subdomain() -> None:
    """Subdomains should not match the exact parent domain config."""
    manager = DomainBudgetManager()
    # api.grants.gov is not in DEFAULTS, so should get default (2)
    assert manager.acquire("https://api.grants.gov/opp/1") is True
    assert manager.acquire("https://api.grants.gov/opp/2") is True
    assert manager.acquire("https://api.grants.gov/opp/3") is False


# ---------------------------------------------------------------------------
# clear() resets state
# ---------------------------------------------------------------------------


def test_clear_resets_budget() -> None:
    """clear() should reset all slots and timestamps."""
    manager = DomainBudgetManager()
    assert manager.acquire("https://minciencias.gov.co/a") is True
    assert manager.acquire("https://minciencias.gov.co/b") is False  # exhausted
    assert manager.acquire("https://example.com/a") is True

    manager.clear()

    # Both domains should be fresh
    assert manager.acquire("https://minciencias.gov.co/a") is True
    assert manager.acquire("https://minciencias.gov.co/b") is False  # still 1 slot max
    assert manager.acquire("https://example.com/a") is True
    assert manager.acquire("https://example.com/b") is True
    assert manager.acquire("https://example.com/c") is False


def test_delay_resets_after_clear() -> None:
    """After clear(), delay_for() should return 0.0 even if there was a prior request."""
    manager = DomainBudgetManager()
    manager.acquire("https://minciencias.gov.co/a")
    manager.release("https://minciencias.gov.co/a")

    # Has a last_request_time from before
    manager.clear()

    # After clear, delay should be 0
    assert manager.delay_for("https://minciencias.gov.co/b") == 0.0
