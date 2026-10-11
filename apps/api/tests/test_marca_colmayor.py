"""T6 Colmayor brand line in reports (TDD).

The HTML report must carry the Colegio Mayor institutional identity:
brand color tokens sampled from the shield, the resized logo embedded as
base64 (no network), and the membrete typeface with a system fallback.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from types import SimpleNamespace

from app.services import export as export_mod
from app.services.export import generate_report_html

BRAND_DIR = Path(export_mod.__file__).resolve().parent.parent / "assets" / "brand" / "colmayor"

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _opp(title="Call A"):
    return SimpleNamespace(
        source_id="src-1",
        status="open",
        country="Colombia",
        title=title,
        entity="Test Entity",
        summary="Summary",
        description="",
        close_date=None,
        funding_amount_raw="",
        funding_amount_value=None,
        categories=[],
        official_url="",
        application_url=None,
    )


class TestBrandTokens:
    def test_primary_and_accent_are_valid_hex(self):
        for token in (
            export_mod._BRAND_PRIMARY,
            export_mod._BRAND_SECONDARY,
            export_mod._BRAND_ACCENT,
            export_mod._BRAND_GOLD,
        ):
            assert HEX_RE.match(token), f"not a hex color: {token!r}"

    def test_tokens_match_colmayor_shield(self):
        assert export_mod._BRAND_PRIMARY.lower() == "#018383"  # shield teal
        assert export_mod._BRAND_GOLD.lower() == "#fea101"  # shield gold
        assert export_mod._BRAND_ACCENT.lower() == "#015b5c"  # dark teal

    def test_font_is_membrete_typeface_with_system_fallback(self):
        font = export_mod._BRAND_FONT
        assert "calibri" in font.lower()
        assert "system-ui" in font


class TestBrandAssets:
    def test_logo_exists_and_is_lightweight(self):
        logo = BRAND_DIR / "logo.jpg"
        assert logo.is_file(), f"missing {logo}"
        assert logo.stat().st_size < 150 * 1024
        from PIL import Image

        with Image.open(logo) as im:
            assert im.width <= 800

    def test_favicon_exists_and_is_lightweight(self):
        favicon = BRAND_DIR / "favicon.png"
        assert favicon.is_file(), f"missing {favicon}"
        assert favicon.stat().st_size < 150 * 1024
        from PIL import Image

        with Image.open(favicon) as im:
            assert im.size == (64, 64)


class TestReportCarriesBrand:
    def test_html_embeds_colmayor_logo(self):
        html = generate_report_html("Report", SimpleNamespace(name="Org"), [_opp()])
        assert "data:image/jpeg;base64," in html
        assert "Colmayor" in html or "COLEGIO MAYOR" in html

    def test_html_uses_brand_colors(self):
        html = generate_report_html("Report", SimpleNamespace(name="Org"), [_opp()])
        assert export_mod._BRAND_PRIMARY.lower() in html.lower()
        assert export_mod._BRAND_GOLD.lower() in html.lower()

    def test_html_needs_no_network(self):
        html = generate_report_html("Report", SimpleNamespace(name="Org"), [_opp()])
        assert "fonts.googleapis.com" not in html
        assert "fonts.gstatic.com" not in html

    def test_logo_b64_decodes_to_jpeg(self):
        raw = base64.b64decode(export_mod._LOGO_B64)
        assert raw[:2] == b"\xff\xd8"  # JPEG magic bytes
