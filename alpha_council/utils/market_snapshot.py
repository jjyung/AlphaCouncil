"""Market snapshot tool — current price, volatility, and position guidance.

Designed for downstream decision agents (trader, risk debaters, portfolio
manager) to ground their recommendations in real numeric data rather than
LLM-guessed figures. Returns a single JSON blob covering:

    - current price + 52-week range
    - daily / annualised volatility + ATR-14
    - volatility-adjusted suggested position % (ported from
      ai-hedge-fund's `calculate_volatility_adjusted_limit`)
    - stop-loss suggestion (entry − 2×ATR)

Uses yfinance (already a project dependency).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_TZ_TW = ZoneInfo("Asia/Taipei")

# In-process cache to dedupe yfinance calls within a single pipeline run.
# Keyed by (ticker_upper, market_normalized, iso_date).
_snapshot_cache: dict[tuple[str, str, str], str] = {}


def _now_iso() -> str:
    return dt.datetime.now(_TZ_TW).isoformat()


def _normalize_market(market: str) -> str:
    m = (market or "").strip().lower()
    if m not in {"us", "tw", ""}:
        raise ValueError("market must be 'us', 'tw', or '' (defaults to 'us')")
    return m or "us"


def _tw_symbol_candidates(ticker: str) -> list[str]:
    """Mirror of technical_analyst's candidate resolution for TW tickers."""
    t = ticker.strip().upper()
    if t.endswith(".TW") or t.endswith(".TWO"):
        return [t]
    if t.isdigit():
        return [f"{t}.TW", f"{t}.TWO"]
    return [t]


def _fetch_history(ticker: str, market: str) -> tuple[pd.DataFrame, str]:
    """Return 1-year daily OHLCV and the resolved yfinance symbol."""
    candidates = [ticker.strip().upper()] if market == "us" else _tw_symbol_candidates(ticker)
    errors: list[str] = []
    for symbol in candidates:
        try:
            df = yf.Ticker(symbol).history(period="1y", auto_adjust=False)
            if df is not None and not df.empty:
                return df, symbol
        except Exception as e:  # noqa: BLE001
            errors.append(f"{symbol}: {e}")
    raise RuntimeError(
        f"No price data for ticker {ticker!r} (market={market}). Tried: {candidates}. "
        f"Errors: {errors or 'empty frames'}"
    )


def _atr_14(df: pd.DataFrame) -> float | None:
    """Classic Wilder-style ATR-14, returned as a single latest value."""
    if len(df) < 15:
        return None
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close_prev = df["Close"].astype(float).shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - close_prev).abs(), (low - close_prev).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(window=14, min_periods=14).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else None


def _vol_band(annualized: float | None) -> str:
    if annualized is None:
        return "unknown"
    if annualized < 0.15:
        return "low"
    if annualized < 0.30:
        return "medium"
    if annualized < 0.50:
        return "high"
    return "very_high"


def _suggested_position_pct(annualized_vol: float | None) -> float:
    """Volatility-adjusted single-name position limit.

    Ported from ai-hedge-fund `calculate_volatility_adjusted_limit`:
        <15%       → ~25% (low vol, can allocate more)
        15%-30%    → 20% → 12.5% (linear taper)
        30%-50%    → 15% → 5%    (steeper reduction)
        >50%       →  10% cap    (very high vol)
    Base = 20%, multiplier bounded to [0.25, 1.25].
    """
    if annualized_vol is None:
        return 0.10  # Unknown vol → conservative default
    base_limit = 0.20
    if annualized_vol < 0.15:
        multiplier = 1.25
    elif annualized_vol < 0.30:
        multiplier = 1.0 - (annualized_vol - 0.15) * 0.5
    elif annualized_vol < 0.50:
        multiplier = 0.75 - (annualized_vol - 0.30) * 0.5
    else:
        multiplier = 0.50
    multiplier = max(0.25, min(1.25, multiplier))
    return round(base_limit * multiplier, 4)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        f = float(v)
        return f if not np.isnan(f) and not np.isinf(f) else None
    except (TypeError, ValueError):
        return None


def get_market_snapshot(ticker: str, market: str = "tw") -> str:
    """Fetch a real-time market snapshot for decision agents.

    Args:
        ticker: Stock symbol, e.g. "2330", "2330.TW", "AAPL".
        market: "tw" (default) or "us".

    Returns:
        JSON string with fields:
            ok, ticker, market, resolved_symbol, as_of_date, fetched_at,
            price: {current, 52w_high, 52w_low, from_52w_high_pct, from_52w_low_pct},
            volatility: {daily, annualized, atr_14, vol_band},
            position_guidance: {suggested_max_position_pct, rationale,
                                stop_loss: {atr_multiple, offset_per_share,
                                            suggested_stop_price}},
            warnings: list[str],
            data_source: "yfinance",
            error (only when ok=false).
    """
    warnings: list[str] = []
    try:
        market_norm = _normalize_market(market)
    except ValueError as e:
        return json.dumps({"ok": False, "ticker": ticker, "error": str(e)}, ensure_ascii=False, indent=2)

    # Cache lookup: same ticker+market+date within one process hits once.
    today = dt.datetime.now(_TZ_TW).date().isoformat()
    cache_key = (ticker.strip().upper(), market_norm, today)
    if cache_key in _snapshot_cache:
        return _snapshot_cache[cache_key]

    try:
        df, resolved_symbol = _fetch_history(ticker, market_norm)
    except Exception as e:  # noqa: BLE001
        logger.exception("get_market_snapshot: fetch failed for %s", ticker)
        return json.dumps(
            {
                "ok": False,
                "ticker": ticker,
                "market": market_norm,
                "fetched_at": _now_iso(),
                "error": str(e),
            },
            ensure_ascii=False,
            indent=2,
        )

    close = df["Close"].astype(float)
    current_price = _safe_float(close.iloc[-1])
    high_52w = _safe_float(df["High"].astype(float).max())
    low_52w = _safe_float(df["Low"].astype(float).min())
    as_of = df.index[-1]
    as_of_date = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)[:10]

    returns = close.pct_change().dropna()
    if len(returns) < 2:
        warnings.append("Insufficient return history for volatility calculation.")
        daily_vol = None
        annualized_vol = None
    else:
        lookback = returns.tail(60)  # match ai-hedge-fund's 60-day window
        daily_vol = _safe_float(lookback.std())
        annualized_vol = _safe_float(daily_vol * np.sqrt(252)) if daily_vol is not None else None

    atr = _atr_14(df)
    if atr is None:
        warnings.append("ATR-14 not computable (<15 rows of data).")

    vol_band = _vol_band(annualized_vol)
    suggested_pct = _suggested_position_pct(annualized_vol)

    stop_offset = round(atr * 2.0, 4) if atr is not None else None
    stop_price = (
        round(current_price - stop_offset, 4)
        if current_price is not None and stop_offset is not None
        else None
    )

    from_high_pct = (
        round((current_price - high_52w) / high_52w, 4)
        if current_price is not None and high_52w not in (None, 0)
        else None
    )
    from_low_pct = (
        round((current_price - low_52w) / low_52w, 4)
        if current_price is not None and low_52w not in (None, 0)
        else None
    )

    rationale = (
        f"Annualised volatility {annualized_vol:.1%} → band '{vol_band}' → "
        f"suggested max position {suggested_pct:.1%} of portfolio."
        if annualized_vol is not None
        else f"Volatility unknown → conservative default {suggested_pct:.1%}."
    )

    result = json.dumps(
        {
            "ok": True,
            "ticker": ticker,
            "market": market_norm,
            "resolved_symbol": resolved_symbol,
            "as_of_date": as_of_date,
            "fetched_at": _now_iso(),
            "price": {
                "current": current_price,
                "52w_high": high_52w,
                "52w_low": low_52w,
                "from_52w_high_pct": from_high_pct,
                "from_52w_low_pct": from_low_pct,
            },
            "volatility": {
                "daily": round(daily_vol, 6) if daily_vol is not None else None,
                "annualized": round(annualized_vol, 4) if annualized_vol is not None else None,
                "atr_14": round(atr, 4) if atr is not None else None,
                "vol_band": vol_band,
            },
            "position_guidance": {
                "suggested_max_position_pct": suggested_pct,
                "rationale": rationale,
                "stop_loss": {
                    "atr_multiple": 2.0,
                    "offset_per_share": stop_offset,
                    "suggested_stop_price": stop_price,
                },
            },
            "warnings": warnings,
            "data_source": "yfinance",
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    _snapshot_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Helpers for injecting snapshot as prompt context (avoids LLM tool-call
# ambiguity inside LoopAgents where sibling sub-agents share history).
# ---------------------------------------------------------------------------

_TICKER_PATTERN = re.compile(r"\*{0,2}標的\*{0,2}\s*[：:]\s*([0-9A-Za-z][\w\.]*)")
_MARKET_PATTERN = re.compile(r"\*{0,2}市場\*{0,2}\s*[：:]\s*(tw|us|TW|US)")


def _parse_ticker_from_state(state: Any) -> tuple[str, str]:
    """Best-effort: pull ticker + market from any analyst report already in state.

    Returns ("", "tw") when nothing is found.
    """
    for key in ("technical_report", "fundamentals_report", "chip_report",
                "psychology_report", "news_report"):
        report = state.get(key, "") if hasattr(state, "get") else ""
        if not report:
            continue
        t_match = _TICKER_PATTERN.search(report)
        if not t_match:
            continue
        ticker = t_match.group(1).strip()
        m_match = _MARKET_PATTERN.search(report)
        market = m_match.group(1).lower() if m_match else "tw"
        return ticker, market
    return "", "tw"


def build_snapshot_context(state: Any) -> str:
    """Fetch (or cache-hit) the snapshot and format as a prompt block.

    Returns "" when ticker cannot be resolved from state.
    """
    ticker, market = _parse_ticker_from_state(state)
    if not ticker:
        return ""
    snapshot_json = get_market_snapshot(ticker, market)
    return (
        "【市場即時快照 — 請以此數據為基礎，不需再呼叫工具】\n"
        f"```json\n{snapshot_json}\n```"
    )
