from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.generic_html import GenericHtmlConnector
from app.connectors.pdf import PdfConnector
from app.connectors.rss import RssConnector


class HybridConnector:
    def __init__(self, source_key: str, base_url: str) -> None:
        self.source_key = source_key
        self.base_url = base_url

    def _delegate(self, raw: RawSourceResult | None = None):
        lowered = self.base_url.lower()
        content_type = (raw.content_type.lower() if raw and raw.content_type else "") if raw else ""
        content = raw.content.lstrip() if raw else ""
        if "rss" in content_type or lowered.endswith((".rss", ".xml")) or content.startswith("<rss") or content.startswith("<?xml"):
            return RssConnector(self.source_key, self.base_url)
        if "pdf" in content_type or lowered.endswith(".pdf") or content.startswith("%PDF"):
            return PdfConnector(self.source_key, self.base_url)
        return GenericHtmlConnector(self.source_key, self.base_url)

    async def fetch(self) -> RawSourceResult:
        delegate = self._delegate()
        raw = await delegate.fetch()
        raw.metadata["hybrid_delegate"] = delegate.__class__.__name__
        return raw

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        return await self._delegate(raw).parse(raw)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return await self._delegate().validate(candidate)
