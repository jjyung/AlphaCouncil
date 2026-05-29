"""Unit tests for alpha_council.utils.decision_history."""

from __future__ import annotations

import json
from pathlib import Path

from alpha_council.utils.decision_history import (
    format_previous_decision_for_prompt,
    load_previous_decision,
    save_decision,
)


class TestSaveAndLoad:
    """save_decision + load_previous_decision round-trip."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """Write one record, read it back."""
        save_decision("AAPL", "us", "sess_001", "BUY at 15%", root=tmp_path)
        record = load_previous_decision("AAPL", "us", root=tmp_path)
        assert record is not None
        assert record["ticker"] == "AAPL"
        assert record["market"] == "us"
        assert record["session_id"] == "sess_001"
        assert record["full_text"] == "BUY at 15%"
        assert "date" in record

    def test_append_then_read_last(self, tmp_path: Path) -> None:
        """Multiple writes: only last record is returned."""
        save_decision("AAPL", "us", "sess_001", "First decision", root=tmp_path)
        save_decision("AAPL", "us", "sess_002", "Second decision", root=tmp_path)
        record = load_previous_decision("AAPL", "us", root=tmp_path)
        assert record is not None
        assert record["session_id"] == "sess_002"
        assert record["full_text"] == "Second decision"

    def test_no_history(self, tmp_path: Path) -> None:
        """No file → None returned."""
        record = load_previous_decision("MSFT", "us", root=tmp_path)
        assert record is None

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty file → None returned."""
        path = tmp_path / "us" / "MSFT" / "decision_history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        record = load_previous_decision("MSFT", "us", root=tmp_path)
        assert record is None

    def test_per_ticker_isolation(self, tmp_path: Path) -> None:
        """Different tickers do not interfere."""
        save_decision("AAPL", "us", "s1", "AAPL decision", root=tmp_path)
        save_decision("MSFT", "us", "s2", "MSFT decision", root=tmp_path)
        aapl = load_previous_decision("AAPL", "us", root=tmp_path)
        msft = load_previous_decision("MSFT", "us", root=tmp_path)
        assert aapl is not None and aapl["full_text"] == "AAPL decision"
        assert msft is not None and msft["full_text"] == "MSFT decision"


class TestFormatPreviousDecision:
    """format_previous_decision_for_prompt."""

    def test_basic_format(self) -> None:
        record = {"date": "2026-05-22", "full_text": "BUY at 15%"}
        result = format_previous_decision_for_prompt(record)
        assert "2026-05-22" in result
        assert "BUY at 15%" in result
        assert "上次投資決策記錄" in result

    def test_empty_text(self) -> None:
        result = format_previous_decision_for_prompt({"date": "x", "full_text": ""})
        assert result == ""

    def test_whitespace_text(self) -> None:
        result = format_previous_decision_for_prompt({"date": "x", "full_text": "   "})
        assert result == ""


class TestFileStructure:
    """Verify the JSON Lines file structure."""

    def test_jsonl_format(self, tmp_path: Path) -> None:
        save_decision("AAPL", "us", "s1", "line1", root=tmp_path)
        save_decision("AAPL", "us", "s2", "line2", root=tmp_path)
        path = tmp_path / "us" / "AAPL" / "decision_history.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["full_text"] == "line1"
        assert json.loads(lines[1])["full_text"] == "line2"

    def test_ensure_ascii_off(self, tmp_path: Path) -> None:
        """Chinese text is preserved, not \\u escaped."""
        save_decision("2330", "tw", "s1", "買入", root=tmp_path)
        path = tmp_path / "tw" / "2330" / "decision_history.jsonl"
        content = path.read_text(encoding="utf-8")
        assert "買入" in content
        assert "\\u" not in content
