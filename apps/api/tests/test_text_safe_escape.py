"""Unit tests for app.core.text.safe_escape.

Pins the unescape-then-escape contract used by report/digest HTML generation:
scraped content may already contain HTML entities (``&aacute;``, ``&ntilde;``,
``&amp;``) inherited from the original pages. A plain ``html.escape`` would
double-escape them into literal ``&amp;aacute;`` garbage in rendered reports.
The helper must decode entities exactly once and then escape exactly once so
active markup (``<script>``) stays neutralized.
"""

from __future__ import annotations

from app.core.text import safe_escape


class TestSafeEscapeContract:
    def test_pre_encoded_entity_is_decoded_not_double_escaped(self) -> None:
        assert safe_escape("Fundaci&oacute;n") == "Fundación"

    def test_active_markup_is_neutralized(self) -> None:
        assert safe_escape("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_plain_ampersand_is_escaped_exactly_once(self) -> None:
        assert safe_escape("R&D") == "R&amp;D"

    def test_none_and_empty_render_empty_string(self) -> None:
        assert safe_escape(None) == ""
        assert safe_escape("") == ""

    def test_already_escaped_markup_survives_round_trip_identically(self) -> None:
        # unescape("<i>&") then escape must reproduce the same encoding,
        # proving there is no runaway double-decoding of hostile input.
        assert safe_escape("&lt;i&gt;&amp;") == "&lt;i&gt;&amp;"
