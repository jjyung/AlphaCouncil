"""Decision history persistence for portfolio_manager continuity.

Saves each run's portfolio_manager decision to a per-ticker JSON Lines file
so that subsequent runs can reference the previous decision, ensuring
consistency and continuity across investment decisions.

File layout:
    reports/{market}/{ticker}/decision_history.jsonl

Each line is one JSON object with ticker, market, date, session_id, full_text.
The file is append-only; the last complete line is the most recent decision.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path("reports")


def _history_path(ticker: str, market: str, *, root: Path = _DEFAULT_ROOT) -> Path:
    return root / market / ticker / "decision_history.jsonl"


def save_decision(
    ticker: str,
    market: str,
    session_id: str,
    decision_text: str,
    *,
    root: Path = _DEFAULT_ROOT,
) -> str:
    """Append a decision record to the local history file.

    Args:
        ticker: Stock ticker, e.g. "AAPL" or "2330".
        market: Market code, "us" or "tw".
        session_id: Unique session identifier for this run.
        decision_text: Full output text from portfolio_manager.
        root: Base directory (defaults to ``./reports``).

    Returns:
        Absolute path of the history file written to.
    """
    path = _history_path(ticker, market, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ticker": ticker,
        "market": market,
        "date": datetime.now(UTC).date().isoformat(),
        "session_id": session_id,
        "full_text": decision_text,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Decision history appended: %s", path)
    return str(path.resolve())


def load_previous_decision(
    ticker: str,
    market: str,
    *,
    root: Path = _DEFAULT_ROOT,
) -> dict[str, Any] | None:
    """Load the most recent decision record for *ticker*.

    Scans the append-only JSON Lines file and returns the last complete
    record, or ``None`` if the file does not exist or is empty.

    Args:
        ticker: Stock ticker, e.g. "AAPL" or "2330".
        market: Market code, "us" or "tw".
        root: Base directory (defaults to ``./reports``).

    Returns:
        A dict with keys ``ticker``, ``market``, ``date``, ``session_id``,
        ``full_text``, or ``None``.
    """
    path = _history_path(ticker, market, root=root)
    if not path.exists():
        logger.debug("No decision history for %s/%s — file not found.", market, ticker)
        return None

    last_record: dict[str, Any] | None = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                last_record = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed line in %s", path)
                continue

    if last_record is None:
        logger.debug("No decision history for %s/%s — empty file.", market, ticker)
    return last_record


def format_previous_decision_for_prompt(record: dict[str, Any]) -> str:
    """Format a previous decision record as a prompt context block.

    The output is a markdown block designed to be injected into
    ``portfolio_manager``'s instruction as optional reference material.

    Args:
        record: A dict returned by :func:`load_previous_decision`.

    Returns:
        A formatted string ready to prepend to the agent instruction.
    """
    date = record.get("date", "?")
    text = record.get("full_text", "").strip()

    if not text:
        return ""

    return (
        "【上次投資決策記錄 — 僅供參考，請評估延續性】\n\n"
        f"上次分析日期：{date}\n\n"
        f"上次完整決策內容：\n"
        f"```\n{text}\n```\n\n"
        "⚠️ 注意事項：\n"
        "1. 以上為過往決策記錄，市場條件可能已改變，請勿盲目追隨\n"
        "2. 若上次為買入，應考慮既有曝險是否仍合理\n"
        "3. 若上次為賣出，應確認觸發原因是否已解除或持續\n"
        "4. 請明確說明本次決策與上次的關係：延續、調整或反轉，並附理由\n"
    )
