"""eval_extraction --check N limits coverage sample size only (not 18% gate)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_PATH = REPO_ROOT / "scripts" / "eval_extraction.py"


def _load_eval():
    spec = importlib.util.spec_from_file_location("eval_extraction", EVAL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEvalCheckLimit:
    def test_check_n_limits_query_to_n(self):
        mod = _load_eval()
        query = MagicMock()
        query.limit.return_value = query
        query.all.return_value = []
        db = MagicMock()
        db.query.return_value = query

        with patch.object(mod, "SessionLocal", return_value=db, create=True):
            # Prefer public API if present; fall back to _load_opps(limit=...)
            if hasattr(mod, "_load_opps"):
                # Patch imports used inside _load_opps
                with patch.dict("sys.modules", {}):
                    pass
            result_limit = None

            def capture_limit(n):
                nonlocal result_limit
                result_limit = n
                return query

            query.limit.side_effect = capture_limit

            # Call through argparse path with monkeypatched DB
            with patch("app.db.session.SessionLocal", return_value=db):
                with patch("app.models.Opportunity", MagicMock()):
                    mod._load_opps(check=20)

            assert result_limit == 20
            query.limit.assert_called_with(20)

    def test_omitted_check_uses_default_5000(self):
        mod = _load_eval()
        query = MagicMock()
        query.all.return_value = []
        db = MagicMock()
        db.query.return_value = query
        seen: list[int] = []

        def capture_limit(n):
            seen.append(n)
            return query

        query.limit.side_effect = capture_limit

        with patch("app.db.session.SessionLocal", return_value=db):
            with patch("app.models.Opportunity", MagicMock()):
                mod._load_opps(check=None)

        assert seen == [5000]

    def test_check_does_not_enable_strict_or_eighteen_gate(self):
        mod = _load_eval()
        # Parse argv: --check alone must not imply --strict, and default threshold stays 60
        # (not the 023 18% corpus coverage gate).
        args = mod.build_arg_parser().parse_args(["--check", "20"])
        assert args.check == 20
        assert getattr(args, "strict", False) is False
        assert args.threshold == 60.0
        assert args.threshold != 18.0

    def test_check_zero_or_negative_falls_back_to_5000(self):
        mod = _load_eval()
        query = MagicMock()
        query.all.return_value = []
        db = MagicMock()
        db.query.return_value = query
        seen: list[int] = []

        def capture_limit(n):
            seen.append(n)
            return query

        query.limit.side_effect = capture_limit

        with patch("app.db.session.SessionLocal", return_value=db):
            with patch("app.models.Opportunity", MagicMock()):
                mod._load_opps(check=0)
                mod._load_opps(check=-5)

        assert seen == [5000, 5000]
