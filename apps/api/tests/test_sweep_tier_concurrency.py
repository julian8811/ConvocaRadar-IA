"""T3 (fortalecer-201): per-tier sweep concurrency (strategy a).

Pins the reversible tier split of the scheduler sweep:

- ``Settings.tier_concurrency``: 3/2/1 defaults (sum == legacy pool of 6),
  env opt-in per tier, clamped to [1, global cap] so defaults can never
  exceed today's prod load.
- ``partition_by_tier``: buckets an already priority-ordered due list,
  order preserved within each bucket, untiered/unknown → experimental
  (lowest priority, still runs — no starvation).

Pure unit tests with SimpleNamespace sources — no DB, no event loop.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import Settings
from app.scraper.priority_queue import partition_by_tier, tier_bucket


def _settings(**overrides) -> Settings:
    base = {
        "jwt_secret": "x" * 32,
        "internal_api_key": "y" * 32,
        "scraping_max_concurrency": 6,
        "scraping_max_concurrency_strategic": None,
        "scraping_max_concurrency_complementary": None,
        "scraping_max_concurrency_experimental": None,
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def _src(key: str, tier: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=key, key=key, tier=tier)


class TestTierConcurrencyDefaults:
    def test_defaults_sum_to_legacy_pool(self) -> None:
        settings = _settings()

        assert settings.tier_concurrency("strategic") == 3
        assert settings.tier_concurrency("complementary") == 2
        assert settings.tier_concurrency("experimental") == 1

    def test_env_override_per_tier(self) -> None:
        settings = _settings(scraping_max_concurrency_strategic=5)

        assert settings.tier_concurrency("strategic") == 5
        # Untouched tiers keep defaults.
        assert settings.tier_concurrency("complementary") == 2
        assert settings.tier_concurrency("experimental") == 1

    def test_clamped_to_global_cap(self) -> None:
        """A typo'd env (or a lowered global) can't exceed prod load."""
        settings = _settings(
            scraping_max_concurrency=2,
            scraping_max_concurrency_strategic=99,
        )

        assert settings.global_concurrency_cap() == 2
        assert settings.tier_concurrency("strategic") == 2
        assert settings.tier_concurrency("complementary") == 2
        assert settings.tier_concurrency("experimental") == 1

    def test_minimum_one(self) -> None:
        settings = _settings(scraping_max_concurrency_experimental=0)

        assert settings.tier_concurrency("experimental") == 1


class TestPartitionByTier:
    def test_buckets_keep_priority_order(self) -> None:
        ordered = [
            _src("s1", "strategic"),
            _src("s2", "strategic"),
            _src("c1", "complementary"),
            _src("e1", "experimental"),
            _src("c2", "complementary"),
        ]

        buckets = partition_by_tier(ordered)

        assert [s.key for s in buckets["strategic"]] == ["s1", "s2"]
        assert [s.key for s in buckets["complementary"]] == ["c1", "c2"]
        assert [s.key for s in buckets["experimental"]] == ["e1"]

    def test_untiered_and_unknown_share_experimental_bucket(self) -> None:
        ordered = [_src("u1", None), _src("u2", ""), _src("u3", "weird")]

        buckets = partition_by_tier(ordered)

        assert buckets["strategic"] == []
        assert buckets["complementary"] == []
        assert [s.key for s in buckets["experimental"]] == ["u1", "u2", "u3"]
        assert tier_bucket(None) == "experimental"
        assert tier_bucket("STRATEGIC") == "strategic"

    def test_strategic_first_gather_order(self) -> None:
        """The scheduler gathers bucket-by-bucket: strategic always first."""
        ordered = [
            _src("e1", "experimental"),
            _src("c1", "complementary"),
            _src("s1", "strategic"),
        ]
        buckets = partition_by_tier(ordered)

        gather_order = [
            s.key
            for tier in ("strategic", "complementary", "experimental")
            for s in buckets[tier]
        ]

        assert gather_order == ["s1", "c1", "e1"]
