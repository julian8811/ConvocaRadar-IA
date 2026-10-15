"""Skip re-scrape when the listing page did not change (fingerprint).

Context: static catalogs (novo 2188 found/0 created, sdde) pay full
fetch+parse+validate every day with zero new items. The DOM hash already
tracked per source becomes a skip decision: identical hash ⇒ return no
candidates before parse. Embedded payloads (ld+json/__NEXT_DATA__, which
parse Step 1 consumes but normalize strips) are hashed separately so a
data-only change is never missed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import Opportunity, Organization, Source


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


HTML = """<html><body><main>
<article><h2><a href="/convocatorias/beca-salud-2026">Beca de salud 2026</a></h2></article>
</main></body></html>"""

HTML_WITH_CALL = HTML.replace(
    "</main>",
    '<article><h2><a href="/convocatorias/beca-nueva-2026">Beca nueva 2026</a></h2></article></main>',
)


def _fake_connector(calls: list, html: str = HTML) -> object:
    from app.connectors.base import RawSourceResult, ValidationResult
    from app.connectors.configurable_html import ConfigurableHtmlConnector

    real = ConfigurableHtmlConnector(
        "fp-skip-src",
        "https://example.com/convocatorias",
        {
            "list_selectors": ["a[href*='/convocatorias/']"],
            "title_selectors": ["a"],
            "link_selectors": ["a"],
            "content_selectors": ["main"],
            "date_labels": ["Cierre:"],
        },
        entity_name="FP",
        default_country="Colombia",
    )

    async def _fetch():
        return RawSourceResult(
            source_key="fp-skip-src", url="https://example.com/convocatorias", content=html
        )

    async def _parse(raw):
        calls.append(1)
        return await real.parse(raw)

    async def _validate(candidate):
        return ValidationResult(ok=True)

    return SimpleNamespace(
        fetch=_fetch, parse=_parse, validate=_validate, get_updated_config=lambda: None,
    )


def _source(db: Session) -> Source:
    source = Source(
        name="fp", key="fp-skip-src", base_url="https://example.com/convocatorias",
    )
    db.add(source)
    db.commit()
    return source


class TestDomUnchangedSkip:
    async def test_identical_second_scrape_skips_parse(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.scraper.runner import run_source_inline

        source = _source(db)
        calls: list = []

        def _factory(*_args, **_kwargs):
            return _fake_connector(calls)

        monkeypatch.setattr("app.connectors.factory.connector_for", _factory)

        first = await run_source_inline(db, source)
        assert first.status == "success"
        assert len(calls) == 1

        second = await run_source_inline(db, source)
        assert second.status == "success"
        assert len(calls) == 1, "unchanged page must not be re-parsed"
        assert (
            db.scalar(select(Opportunity).where(Opportunity.source_id == source.id)) is not None
        )

    async def test_changed_page_parses_again(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.scraper.runner import run_source_inline

        source = _source(db)
        calls: list = []
        html_box = [HTML]

        def _factory(*_args, **_kwargs):
            return _fake_connector(calls, html_box[0])

        monkeypatch.setattr("app.connectors.factory.connector_for", _factory)
        await run_source_inline(db, source)
        html_box[0] = HTML_WITH_CALL
        await run_source_inline(db, source)
        assert len(calls) == 2


class TestListingHash:
    def test_embedded_only_change_alters_hash(self) -> None:
        from app.scraper.dom_monitor import compute_listing_hash

        base = "<html><body><main><a href='/x'>T</a></main></body></html>"
        with_data = base.replace(
            "</body>", '<script type="application/ld+json">{"@type":"ItemList"}</script></body>'
        )
        assert compute_listing_hash(base) != compute_listing_hash(with_data)

    def test_script_noise_keeps_hash_stable(self) -> None:
        from app.scraper.dom_monitor import compute_listing_hash

        base = "<html><body><main><a href='/x'>T</a></main></body></html>"
        noisy = base.replace(
            "</body>", "<script>var ads=1;/*cmp*/</script><style>.a{color:red}</style></body>"
        )
        assert compute_listing_hash(base) == compute_listing_hash(noisy)
