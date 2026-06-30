"""Tests for the SlidingWindowLimiter used by PR2 (account recovery endpoints).

The limiter backs the ``POST /api/v1/auth/forgot-password`` endpoint, which
must reject the 6th request from the same email within an hour. The limiter
is intentionally in-memory for the MVP (single Render Free web process) and
is designed to be swappable with a Redis-backed implementation later — the
public surface (constructor + ``.check``) is the contract these tests pin
down.

These are unit tests, no database, no FastAPI, no TestClient.
"""

from __future__ import annotations

import threading

from app.core.rate_limit import SlidingWindowLimiter


def test_limiter_allows_first_n_requests_within_window() -> None:
    """The first ``max_requests`` calls inside the window must all return True.

    Trivially small case: 3 requests allowed, all return True. This proves
    the limiter is wired to a counter (not hard-coded to False) and that it
    distinguishes "first call" from "no calls yet" correctly.
    """
    limiter = SlidingWindowLimiter(max_requests=3, window_seconds=60)
    assert limiter.check("alice@example.com") is True
    assert limiter.check("alice@example.com") is True
    assert limiter.check("alice@example.com") is True


def test_limiter_blocks_n_plus_one_request_within_window() -> None:
    """The (max_requests + 1)-th call inside the window must return False.

    This is the core PR2 contract for ``forgot-password``: 5 requests per
    email per hour, 6th is 429. If the comparison is ``>=`` vs ``>`` wrong
    (off-by-one), the 5th or 6th user-visible behavior changes and the
    security review can no longer trust the documented limit.
    """
    limiter = SlidingWindowLimiter(max_requests=5, window_seconds=3600)
    for _ in range(5):
        assert limiter.check("bob@example.com") is True, (
            "SlidingWindowLimiter rejected a request inside the budget — "
            "the limit or the comparison operator is wrong."
        )
    # 6th must be blocked
    assert limiter.check("bob@example.com") is False, (
        "SlidingWindowLimiter allowed the 6th request inside a 5-per-hour "
        "window. The threshold check is wrong (likely >= instead of >)."
    )


def test_limiter_is_independent_per_key() -> None:
    """Hitting the limit on one key must not affect other keys.

    If the limiter shares state across keys (e.g. a single global counter
    instead of a per-key deque), the test fails: alice's exhausted budget
    would block bob's legitimate request, and an attacker could DoS the
    endpoint for all users by spamming a single email.
    """
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=60)
    # Exhaust alice
    assert limiter.check("alice@example.com") is True
    assert limiter.check("alice@example.com") is True
    assert limiter.check("alice@example.com") is False  # alice is throttled
    # Bob must still be allowed
    assert limiter.check("bob@example.com") is True, (
        "SlidingWindowLimiter shared state across keys — bob was blocked "
        "by alice's exhausted budget. This is a cross-user DoS vector."
    )
    assert limiter.check("bob@example.com") is True
    assert limiter.check("bob@example.com") is False  # bob is throttled


def test_limiter_releases_quota_after_window_passes() -> None:
    """After the window elapses, the limiter must allow new requests.

    The check uses ``time.monotonic()``-style timestamps. We can prove the
    window-expiry path by injecting a clock dependency — but to keep the
    surface small we use a tiny window (1 second) and ``time.sleep``.
    1 second of test time is acceptable for a critical contract.
    """
    import time

    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=1)
    assert limiter.check("carol@example.com") is True
    assert limiter.check("carol@example.com") is True
    assert limiter.check("carol@example.com") is False  # throttled
    time.sleep(1.1)  # let the window elapse
    # Old timestamps must have been pruned; new requests are allowed
    assert limiter.check("carol@example.com") is True, (
        "SlidingWindowLimiter did not release quota after the window "
        "elapsed. check() is not pruning old timestamps."
    )


def test_limiter_releases_only_old_timestamps_mixed_window() -> None:
    """When a key has a mix of old + recent timestamps, only recent count toward the budget.

    Scenario: max=2, window=1s. Two hits at t=0, two hits at t=0.5 (the
    second pair is rejected because the first pair still occupies budget).
    After t=1.1 the first pair ages out and one of the new pair can be
    used, leaving room for a fresh hit.
    """
    import time

    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=1)
    # Two hits in window 1
    assert limiter.check("dave@example.com") is True
    assert limiter.check("dave@example.com") is True
    time.sleep(0.5)
    # Third hit during window 1 — rejected (budget exhausted)
    assert limiter.check("dave@example.com") is False
    # After window 1 elapses, the first two ages out, freeing budget
    time.sleep(0.7)  # total ~1.2s since first hit
    # Now the budget is fresh — new request allowed
    assert limiter.check("dave@example.com") is True, (
        "SlidingWindowLimiter did not prune old timestamps before checking "
        "the budget. The sliding window is not actually sliding."
    )


def test_limiter_is_thread_safe() -> None:
    """Concurrent check() calls on the same key must not allow more than max_requests.

    The API runs under uvicorn workers, and async + threads can race on
    the shared state. We use threading.Barrier to maximize the chance of
    a race and assert the post-condition: at most ``max_requests`` of
    the N concurrent calls returned True.
    """
    import concurrent.futures

    limiter = SlidingWindowLimiter(max_requests=5, window_seconds=60)
    n_threads = 50

    barrier = threading.Barrier(n_threads)

    def hit() -> bool:
        # All threads block on the barrier, then race to call check() at
        # the same instant. This maximizes the chance of a TOCTOU bug if
        # the limiter is not thread-safe.
        barrier.wait()
        return limiter.check("eve@example.com")

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as ex:
        results = list(ex.map(lambda _: hit(), range(n_threads)))

    allowed = sum(1 for r in results if r is True)
    blocked = sum(1 for r in results if r is False)
    # Exactly max_requests allowed; the rest blocked. We allow a small
    # tolerance (max_requests - 1 <= allowed <= max_requests) because
    # some threads may finish after the budget is partially consumed
    # but before the prune happens — but in practice the post-condition
    # must be that NO more than max_requests returned True.
    assert blocked == n_threads - 5, (
        f"Thread-safety violation: {allowed} of {n_threads} concurrent "
        f"requests were allowed (max=5). Expected exactly 5. The limiter "
        f"allowed {allowed - 5} extra requests — likely a missing lock."
    )
    assert allowed == 5, (
        f"Expected exactly 5 successful check() calls, got {allowed}. "
        f"Blocked: {blocked}. The budget is being shared incorrectly."
    )
