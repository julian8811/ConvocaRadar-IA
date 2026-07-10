"""Tests for PR 2 — Worker Service + Arq Dual Dispatch.

Strict TDD: tests written FIRST, then implementation.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.models import Organization, Source, SourceRun  # noqa: E402

# Only async tests get the asyncio mark — sync tests are marked explicitly with
# @pytest.mark.asyncio where needed.
_async_only = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _seed():
    """Seed the test DB once per module."""
    seed()


@pytest.fixture
def db(_seed):
    """Provide a clean DB session per test with SourceRuns cleared."""
    session = SessionLocal()
    session.query(SourceRun).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def source(db) -> Source:
    """Return a seeded source for testing."""
    src = db.scalar(select(Source).where(Source.key == "minciencias"))
    assert src is not None, "seeded source 'minciencias' not found"
    return src


@pytest.fixture
def org_id(db) -> str:
    """Return the seeded org ID."""
    org = db.scalar(
        select(Organization).where(Organization.slug == "convocaradar-local")
    )
    assert org is not None, "seeded org not found"
    return str(org.id)


# ===================================================================
# Phase 2.1: Config — redis_url and worker_max_concurrency
# ===================================================================


class TestConfigRedisSettings:
    """RED: Settings must include redis_url and worker_max_concurrency."""

    def test_settings_has_redis_url_default_none(self):
        """redis_url should default to None when not set."""
        from app.core.config import Settings

        settings = Settings(redis_url=None, jwt_secret="a" * 32, internal_api_key="a" * 32)
        assert settings.redis_url is None

    def test_settings_has_worker_max_concurrency_default_4(self):
        """worker_max_concurrency should default to 4."""
        from app.core.config import Settings

        settings = Settings(jwt_secret="a" * 32, internal_api_key="a" * 32)
        assert settings.worker_max_concurrency == 4

    def test_settings_redis_url_can_be_set(self):
        """redis_url should accept a redis:// URL string."""
        from app.core.config import Settings

        settings = Settings(
            redis_url="redis://localhost:6379/0",
            jwt_secret="a" * 32,
            internal_api_key="a" * 32,
        )
        assert settings.redis_url == "redis://localhost:6379/0"


# ===================================================================
# Phase 2.2: Dual Dispatch — dispatcher behavior based on redis_url
# ===================================================================


class TestDispatcherDualDispatch:
    """RED: Dispatcher should enqueue via Arq when redis_url is set,
    and fall back to inline when redis_url is None."""

    @_async_only
    async def test_dispatcher_enqueues_when_redis_url_set(
        self, monkeypatch, db, source, org_id
    ):
        """When settings.redis_url is set, run_source should create an Arq job
        and return immediately (not run inline)."""
        from app.scraper.dispatcher import run_source

        enqueued_jobs = []

        async def mock_enqueue_job(ctx, function, *args, **kwargs):
            enqueued_jobs.append((function, args, kwargs))
            return MagicMock(job_id="test-arq-job-123")

        # Patch redis_url to be set
        monkeypatch.setattr(
            "app.scraper.dispatcher.get_settings",
            lambda: MagicMock(redis_url="redis://localhost:6379/0"),
        )

        # Patch enqueue_job to capture calls
        monkeypatch.setattr(
            "app.scraper.dispatcher.enqueue_job",
            mock_enqueue_job,
        )

        # Patch create_pool to return a mock pool (must be async since create_pool is async)
        mock_pool = AsyncMock()
        async def mock_create_pool(_redis_settings):
            return mock_pool
        monkeypatch.setattr("app.scraper.dispatcher.create_pool", mock_create_pool)

        # Track that inline runner is NOT called
        inline_called = False

        async def never_inline(*_args, **_kwargs):
            nonlocal inline_called
            inline_called = True
            return None

        monkeypatch.setattr("app.scraper.dispatcher.run_source_inline", never_inline)

        # Create a source run that exists so we don't get duplicate skip
        # but we need to clear the running check — actually let's make the
        # existing run check pass by having no running run.
        # The dispatcher will check for existing running run first.
        result = await run_source(db, source, org_id)

        # When enqueued, run_source should create a pending SourceRun
        assert result is not None
        assert result.status == "queued"
        assert inline_called is False

    @_async_only
    async def test_dispatcher_runs_inline_when_redis_url_none(
        self, monkeypatch, db, source, org_id
    ):
        """When settings.redis_url is None, run_source should delegate to
        run_source_inline."""
        from app.scraper.dispatcher import run_source

        inline_calls = []

        async def tracking_inline(_db, _source, _org_id):
            inline_calls.append((_source.key, _org_id))
            run = SourceRun(
                source_id=_source.id,
                status="success",
                started_at=datetime.now(UTC).replace(tzinfo=None),
                finished_at=datetime.now(UTC).replace(tzinfo=None),
                items_found=0,
            )
            return run

        monkeypatch.setattr(
            "app.scraper.dispatcher.run_source_inline", tracking_inline
        )
        # Ensure redis_url is None
        monkeypatch.setattr(
            "app.scraper.dispatcher.get_settings",
            lambda: MagicMock(redis_url=None),
        )

        result = await run_source(db, source, org_id)

        assert result is not None
        assert result.status == "success"
        assert len(inline_calls) == 1
        assert inline_calls[0][0] == source.key


# ===================================================================
# Phase 3.1: Progress column on SourceRun model
# ===================================================================


class TestSourceRunProgressColumn:
    """RED: SourceRun model must have a nullable progress JSON column."""

    def test_source_run_has_progress_column(self):
        """SourceRun model should have a 'progress' column of type dict|None."""
        from app.models import SourceRun

        assert hasattr(SourceRun, "progress")
        # Should be a Mapped column, defaulting to None
        col = SourceRun.__table__.c.get("progress")
        assert col is not None, "progress column missing from source_runs table"
        assert col.nullable, "progress column should be nullable"

    def test_source_run_progress_default_none(self, db):
        """New SourceRun should have progress=None by default."""
        now = datetime.now(UTC).replace(tzinfo=None)
        run = SourceRun(
            source_id="test-source",
            status="running",
            started_at=now,
            logs=[],
        )
        db.add(run)
        db.flush()
        assert run.progress is None


# ===================================================================
# Phase 3.2: Progress updates in runner
# ===================================================================


class TestRunnerProgressUpdates:
    """RED: run_source_inline must update run.progress after each phase."""

    @_async_only
    async def test_runner_updates_progress_after_fetch(
        self, monkeypatch, db, source, org_id
    ):
        """run_source_inline should set progress after fetching candidates."""
        from app.scraper.runner import run_source_inline

        async def mock_scrape_candidates(_source, stats=None):
            if stats is not None:
                stats["candidates_parsed"] = 0
            return []

        def mock_create_opportunity(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            "app.scraper.runner._scrape_candidates", mock_scrape_candidates
        )
        monkeypatch.setattr(
            "app.scraper.runner.create_opportunity", mock_create_opportunity
        )

        run = await run_source_inline(db, source, org_id)

        # After scrape completes, progress should be updated
        assert run.progress is not None
        assert "fetch" in run.progress
        assert "parse" in run.progress
        assert "persist" in run.progress

    @_async_only
    async def test_runner_progress_has_timestamps(
        self, monkeypatch, db, source, org_id
    ):
        """Progress values should be ISO datetime strings."""
        from app.scraper.runner import run_source_inline

        async def mock_scrape_candidates(_source, stats=None):
            if stats is not None:
                stats["candidates_parsed"] = 0
            return []

        monkeypatch.setattr(
            "app.scraper.runner._scrape_candidates", mock_scrape_candidates
        )
        monkeypatch.setattr(
            "app.scraper.runner.create_opportunity", lambda *a, **kw: None
        )

        run = await run_source_inline(db, source, org_id)

        from datetime import datetime as dt

        for step in ("fetch", "parse", "persist"):
            assert step in run.progress, f"Missing progress step: {step}"
            # Verify it's a valid ISO datetime
            dt.fromisoformat(run.progress[step])


# ===================================================================
# Phase 3.3: GET endpoint for run details
# ===================================================================


class TestWorkerRunsEndpoint:
    """RED: GET /api/v1/admin/worker/runs/{run_id} must return SourceRun details."""

    def test_worker_runs_endpoint_registered(self):
        """The endpoint route should be registered in the admin router."""
        from app.api.v1.admin import router

        routes = [r.path for r in router.routes]
        matching = [p for p in routes if "worker" in p and "runs" in p]
        assert len(matching) >= 1, (
            f"No route matching /worker/runs found in admin router. "
            f"Available routes: {routes}"
        )

    def test_worker_runs_endpoint_accepts_run_id_param(self):
        """The route pattern should include a run_id path parameter."""
        from app.api.v1.admin import router

        matching = [
            r.path for r in router.routes if "worker" in r.path and "runs" in r.path
        ]
        assert any("{run_id}" in path for path in matching), (
            f"No route with run_id parameter found in {matching}"
        )

    def test_worker_runs_endpoint_is_get_method(self):
        """The route should accept GET requests."""
        from app.api.v1.admin import router

        matching = [
            r for r in router.routes if "worker" in r.path and "runs" in r.path
        ]
        assert len(matching) >= 1
        # Verify it's a GET route (FastAPI routes have 'methods')
        route = matching[0]
        methods = getattr(route, "methods", None)
        if methods:
            assert "GET" in methods, f"Expected GET method, got {methods}"


# ===================================================================
# Phase 4.2: Dispatcher enqueues when redis_url is set (enqueue path)
# ===================================================================


class TestDispatcherEnqueueBehavior:
    """RED: When redis_url is set, the dispatcher must create a queued SourceRun."""

    @_async_only
    async def test_create_queued_run_has_correct_shape(self):
        """A queued SourceRun should have status='queued' and an arq_job_id."""
        from app.scraper.dispatcher import _create_queued_run
        from app.models import SourceRun

        run = _create_queued_run(
            source_id="test-source-id",
            job_id="test-arq-job-123",
            organization_id="test-org-id",
        )

        assert isinstance(run, SourceRun)
        assert run.status == "queued"
        assert run.source_id == "test-source-id"

    @_async_only
    async def test_enqueue_job_creates_arq_job(self, monkeypatch):
        """enqueue_job should create an Arq job via pool.enqueue_job."""
        from app.scraper.dispatcher import enqueue_job

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="arq-123"))

        job = await enqueue_job(mock_pool, "run_scrape_job", "src-1", "org-1")

        mock_pool.enqueue_job.assert_called_once_with(
            "run_scrape_job", "src-1", "org-1"
        )
        assert job.job_id == "arq-123"


# ===================================================================
# Phase 4.3: Inline fallback when redis_url is not set
# ===================================================================


class TestInlineFallback:
    """RED: When redis_url is None, the dispatcher must fall back to inline."""

    @_async_only
    async def test_dispatcher_falls_back_to_inline_when_no_redis(
        self, monkeypatch, db, source, org_id
    ):
        """Dispatcher should call run_source_inline when redis_url is None."""
        from app.scraper.dispatcher import run_source

        inline_called = False

        async def mock_inline(_db, _source, _org_id):
            nonlocal inline_called
            inline_called = True
            run = SourceRun(
                source_id=_source.id,
                status="success",
                started_at=datetime.now(UTC).replace(tzinfo=None),
                finished_at=datetime.now(UTC).replace(tzinfo=None),
                items_found=0,
            )
            db.add(run)
            db.flush()
            return run

        monkeypatch.setattr(
            "app.scraper.dispatcher.run_source_inline", mock_inline
        )
        monkeypatch.setattr(
            "app.scraper.dispatcher.get_settings",
            lambda: MagicMock(redis_url=None),
        )

        result = await run_source(db, source, org_id)

        assert inline_called, "run_source_inline should be called"
        assert result is not None
        assert result.status == "success"


# ===================================================================
# Phase 4.4: Progress JSON updates correctly
# ===================================================================


class TestProgressJsonStructure:
    """RED: Progress JSON should contain the correct steps and structure."""

    def test_progress_steps_enum(self):
        """Progress keys should be: fetch, parse, persist."""
        from app.scraper.runner import PROGRESS_STEPS

        assert PROGRESS_STEPS == ["fetch", "parse", "persist"]

    @_async_only
    async def test_progress_updated_after_each_step(
        self, monkeypatch, db, source, org_id
    ):
        """run_source_inline should update progress after fetch, parse, and persist."""
        from app.scraper.runner import run_source_inline

        async def mock_scrape(_source, stats=None):
            if stats is not None:
                stats["candidates_parsed"] = 0
            return []

        monkeypatch.setattr(
            "app.scraper.runner._scrape_candidates", mock_scrape
        )
        monkeypatch.setattr(
            "app.scraper.runner.create_opportunity", lambda *a, **kw: None
        )

        run = await run_source_inline(db, source, org_id)

        assert run.progress is not None
        # All three steps must be present
        for step in ("fetch", "parse", "persist"):
            assert step in run.progress, f"Missing progress step: {step}"
            assert isinstance(run.progress[step], str), f"{step} should be a string"
            assert len(run.progress[step]) > 0, f"{step} should not be empty"
