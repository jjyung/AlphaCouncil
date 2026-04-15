import datetime as dt
import json
import time
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from google.adk.agents.llm_agent import Agent
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

_CACHE: dict[str, pd.DataFrame] = {}


def _cache_key(symbol: str, start: str, end: str) -> str:
    return f"{symbol}:{start}:{end}"


def _normalize_market(market: str) -> str:
    m = (market or "").strip().lower()
    if m not in {"us", "tw"}:
        raise ValueError("market must be 'us' or 'tw'")
    return m


def _date_to_iso(date: str | dt.date | dt.datetime) -> str:
    if isinstance(date, dt.datetime):
        return date.date().isoformat()
    if isinstance(date, dt.date):
        return date.isoformat()
    return str(date)


def _parse_date(date: str) -> dt.date:
    try:
        return dt.date.fromisoformat(date)
    except ValueError as exc:
        raise ValueError("date must be ISO format YYYY-MM-DD") from exc


def _default_analysis_date() -> dt.date:
    return dt.datetime.now(ZoneInfo("Asia/Taipei")).date()


def _extract_board_from_symbol(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".TWO"):
        return "otc"
    return "listed"


def _tw_symbol_candidates(ticker: str) -> list[str]:
    t = ticker.strip().upper()
    if t.endswith(".TW") or t.endswith(".TWO"):
        return [t]
    if t.isdigit():
        return [f"{t}.TW", f"{t}.TWO"]
    return [t]


def _to_records(df: pd.DataFrame, limit: int = 90) -> list[dict[str, Any]]:
    if df.empty:
        return []

    subset = df.tail(limit).copy()
    subset = subset.reset_index()
    if "date" not in subset.columns and "Date" in subset.columns:
        subset = subset.rename(columns={"Date": "date"})

    if "date" in subset.columns:
        subset["date"] = pd.to_datetime(subset["date"]).dt.date.astype(str)

    numeric_cols = [
        c for c in ["open", "high", "low", "close", "volume"] if c in subset.columns
    ]
    for col in numeric_cols:
        subset[col] = pd.to_numeric(subset[col], errors="coerce")
        subset[col] = subset[col].replace([np.inf, -np.inf], np.nan)

    for col in ["open", "high", "low", "close"]:
        if col in subset.columns:
            subset[col] = subset[col].round(4)
    if "volume" in subset.columns:
        subset["volume"] = subset["volume"].round(0)

    subset = subset.replace({np.nan: None})
    cols = [
        c for c in ["date", "open", "high", "low", "close", "volume"] if c in subset
    ]
    return subset[cols].to_dict(orient="records")


def _normalize_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = raw.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(c).strip().lower() for c in df.columns]

    rename_map = {
        "adj close": "adj_close",
    }
    df = df.rename(columns=rename_map)

    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = df[required].copy()
    df = df.replace([np.inf, -np.inf], np.nan)

    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert(None)

    df = df.reset_index().rename(columns={"index": "date", "Date": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.drop_duplicates(subset=["date"]).sort_values("date")
    df = df.dropna(subset=["close"])
    return df[["date", "open", "high", "low", "close", "volume"]]


def _download_prices(
    symbol: str, start: str, end: str, retries: int = 3
) -> pd.DataFrame:
    key = _cache_key(symbol, start, end)
    if key in _CACHE:
        return _CACHE[key].copy()

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = yf.download(
                tickers=symbol,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            df = _normalize_ohlcv(raw)
            if not df.empty:
                _CACHE[key] = df.copy()
                return df
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc

        if attempt < retries:
            time.sleep(1.2 * attempt)

    if last_error:
        raise RuntimeError(f"failed to download {symbol}: {last_error}")

    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


def _fetch_stock_data(
    ticker: str,
    start: str,
    end: str,
    market: str,
) -> tuple[pd.DataFrame, str, str]:
    m = _normalize_market(market)

    if m == "us":
        candidates = [ticker.strip().upper()]
    else:
        candidates = _tw_symbol_candidates(ticker)

    errors: list[str] = []
    for symbol in candidates:
        try:
            df = _download_prices(symbol=symbol, start=start, end=end)
            if not df.empty:
                board = _extract_board_from_symbol(symbol) if m == "tw" else "us"
                return df, symbol, board
            errors.append(f"{symbol}: empty")
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    raise RuntimeError(
        f"unable to fetch ticker={ticker}; tried={candidates}; errors={errors}"
    )


def _benchmark_symbol(market: str, board: str = "listed") -> str:
    m = _normalize_market(market)
    if m == "us":
        return "^GSPC"
    if board == "otc":
        return "^TWOII"
    return "^TWII"


def _compute_indicators(price_df: pd.DataFrame) -> pd.DataFrame:
    df = price_df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["ma5"] = SMAIndicator(close=close, window=5).sma_indicator()
    df["ma20"] = SMAIndicator(close=close, window=20).sma_indicator()
    df["ma60"] = SMAIndicator(close=close, window=60).sma_indicator()

    macd_obj = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"] = macd_obj.macd_diff()

    df["rsi14"] = RSIIndicator(close=close, window=14).rsi()

    stoch = StochasticOscillator(
        high=high,
        low=low,
        close=close,
        window=9,
        smooth_window=3,
    )
    df["kd_k"] = stoch.stoch()
    df["kd_d"] = stoch.stoch_signal()

    bb = BollingerBands(close=close, window=20, window_dev=2)
    df["bb_mid"] = bb.bollinger_mavg()
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

    df["volume_ma5"] = df["volume"].rolling(5).mean()
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    return df


def _to_float(v: Any, ndigits: int = 4) -> float | None:
    if v is None:
        return None
    if pd.isna(v):
        return None
    return round(float(v), ndigits)


def _compute_relative_strength(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    window: int = 20,
) -> dict[str, float | None]:
    if stock_df.empty or benchmark_df.empty:
        return {
            "window": window,
            "stock_return": None,
            "benchmark_return": None,
            "spread": None,
        }

    s = stock_df[["date", "close"]].rename(columns={"close": "stock_close"})
    b = benchmark_df[["date", "close"]].rename(columns={"close": "bench_close"})
    merged = s.merge(b, on="date", how="inner").sort_values("date")

    if len(merged) <= window:
        return {
            "window": window,
            "stock_return": None,
            "benchmark_return": None,
            "spread": None,
        }

    stock_ret = (
        merged["stock_close"].iloc[-1] / merged["stock_close"].iloc[-(window + 1)]
    ) - 1
    bench_ret = (
        merged["bench_close"].iloc[-1] / merged["bench_close"].iloc[-(window + 1)]
    ) - 1
    spread = stock_ret - bench_ret

    return {
        "window": window,
        "stock_return": _to_float(stock_ret, 6),
        "benchmark_return": _to_float(bench_ret, 6),
        "spread": _to_float(spread, 6),
    }


def _build_signal_summary(
    indicator_df: pd.DataFrame, rs: dict[str, float | None]
) -> dict[str, str]:
    if len(indicator_df) < 2:
        return {
            "trend": "資料不足，無法判斷趨勢",
            "momentum": "資料不足，無法判斷動能",
            "volatility": "資料不足，無法判斷波動",
            "volume": "資料不足，無法判斷量能",
            "relative_strength": "資料不足，無法判斷相對強弱",
        }

    cur = indicator_df.iloc[-1]
    prev = indicator_df.iloc[-2]

    if pd.notna(cur["ma20"]) and pd.notna(cur["ma60"]):
        if cur["close"] > cur["ma20"] > cur["ma60"]:
            trend = "中期多頭排列（close > MA20 > MA60）"
        elif cur["close"] < cur["ma20"] < cur["ma60"]:
            trend = "中期空頭排列（close < MA20 < MA60）"
        else:
            trend = "均線糾結或過渡期（未形成單一排列）"
    else:
        trend = "均線資料不足，無法完整判讀"

    macd_v = cur.get("macd")
    sig_v = cur.get("macd_signal")
    hist_v = cur.get("macd_hist")
    hist_prev = prev.get("macd_hist")
    if pd.notna(macd_v) and pd.notna(sig_v):
        if (
            macd_v > sig_v
            and pd.notna(hist_v)
            and pd.notna(hist_prev)
            and hist_v > 0
            and hist_prev <= 0
        ):
            momentum = "MACD 黃金交叉且柱狀體轉正，動能改善"
        elif (
            macd_v < sig_v
            and pd.notna(hist_v)
            and pd.notna(hist_prev)
            and hist_v < 0
            and hist_prev >= 0
        ):
            momentum = "MACD 死亡交叉且柱狀體轉負，動能轉弱"
        elif macd_v > sig_v:
            momentum = "MACD 位於訊號線上方，短線動能偏強"
        else:
            momentum = "MACD 位於訊號線下方，短線動能偏弱"
    else:
        momentum = "MACD 資料不足，無法判斷"

    if pd.notna(cur.get("bb_upper")) and pd.notna(cur.get("bb_lower")):
        if cur["close"] >= cur["bb_upper"] * 0.98:
            volatility = "股價接近布林上軌，短線偏熱"
        elif cur["close"] <= cur["bb_lower"] * 1.02:
            volatility = "股價接近布林下軌，短線偏弱"
        else:
            volatility = "股價位於布林通道中段，波動中性"
    else:
        volatility = "布林通道資料不足，無法判讀"

    v5 = cur.get("volume_ma5")
    v20 = cur.get("volume_ma20")
    if pd.notna(v5) and pd.notna(v20) and v20 > 0:
        ratio = float(v5 / v20)
        if ratio >= 1.2:
            volume = "短期量能放大（5日均量顯著高於20日均量）"
        elif ratio <= 0.8:
            volume = "短期量能縮減（5日均量低於20日均量）"
        else:
            volume = "量能變化平穩（5日均量接近20日均量）"
    else:
        volume = "量能資料不足，無法判斷"

    spread = rs.get("spread")
    if spread is None:
        relative_strength = "基準資料不足，無法比較相對強弱"
    elif spread > 0:
        relative_strength = "近20日相對基準為強勢（超額報酬為正）"
    elif spread < 0:
        relative_strength = "近20日相對基準為弱勢（超額報酬為負）"
    else:
        relative_strength = "近20日相對基準持平"

    return {
        "trend": trend,
        "momentum": momentum,
        "volatility": volatility,
        "volume": volume,
        "relative_strength": relative_strength,
    }


def get_stock_data(ticker: str, start: str, end: str, market: str) -> str:
    """Fetch ticker OHLCV via yfinance and return normalized JSON."""
    try:
        _ = _parse_date(start)
        _ = _parse_date(end)
        df, symbol, board = _fetch_stock_data(
            ticker=ticker,
            start=_date_to_iso(start),
            end=_date_to_iso(end),
            market=market,
        )
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "ticker": ticker,
                "market": market,
                "error": str(exc),
                "rows": 0,
                "data": [],
            },
            ensure_ascii=False,
            indent=2,
        )

    payload = {
        "ok": True,
        "ticker": ticker,
        "resolved_symbol": symbol,
        "market": _normalize_market(market),
        "board": board,
        "start": _date_to_iso(start),
        "end": _date_to_iso(end),
        "rows": int(len(df)),
        "data": _to_records(df, limit=120),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def get_market_index(start: str, end: str, market: str, board: str = "listed") -> str:
    """Fetch benchmark index OHLCV via yfinance and return normalized JSON."""
    symbol = _benchmark_symbol(market=market, board=board)
    try:
        _ = _parse_date(start)
        _ = _parse_date(end)
        df = _download_prices(
            symbol=symbol, start=_date_to_iso(start), end=_date_to_iso(end)
        )
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "symbol": symbol,
                "market": market,
                "board": board,
                "error": str(exc),
                "rows": 0,
                "data": [],
            },
            ensure_ascii=False,
            indent=2,
        )

    payload = {
        "ok": True,
        "market": _normalize_market(market),
        "board": board,
        "symbol": symbol,
        "start": _date_to_iso(start),
        "end": _date_to_iso(end),
        "rows": int(len(df)),
        "data": _to_records(df, limit=120),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def get_technical_indicators(
    ticker: str,
    date: str | None = None,
    market: str = "tw",
    lookback_days: int = 180,
) -> str:
    """Return technical indicators and deterministic signals using yfinance + ta."""
    try:
        effective_date = (date or "").strip() if isinstance(date, str) else ""
        analysis_date = (
            _parse_date(effective_date) if effective_date else _default_analysis_date()
        )
        market = (market or "tw").strip().lower() or "tw"

        if lookback_days < 90:
            lookback_days = 90

        start_date = analysis_date - dt.timedelta(days=int(lookback_days * 2.0))
        end_date = analysis_date + dt.timedelta(days=1)

        price_df, resolved_symbol, board = _fetch_stock_data(
            ticker=ticker,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            market=market,
        )

        price_df = price_df[price_df["date"].dt.date <= analysis_date].copy()
        if price_df.empty:
            raise RuntimeError("no OHLCV rows on or before analysis date")

        bench_symbol = _benchmark_symbol(market=market, board=board)
        benchmark_df = _download_prices(
            symbol=bench_symbol,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )
        benchmark_df = benchmark_df[
            benchmark_df["date"].dt.date <= analysis_date
        ].copy()

        indicator_df = _compute_indicators(price_df)
        rs = _compute_relative_strength(price_df, benchmark_df, window=20)
        signals = _build_signal_summary(indicator_df, rs)

        latest = indicator_df.iloc[-1]

        latest_metrics = {
            "date": latest["date"].date().isoformat(),
            "close": _to_float(latest.get("close"), 4),
            "ma5": _to_float(latest.get("ma5"), 4),
            "ma20": _to_float(latest.get("ma20"), 4),
            "ma60": _to_float(latest.get("ma60"), 4),
            "macd": _to_float(latest.get("macd"), 6),
            "macd_signal": _to_float(latest.get("macd_signal"), 6),
            "macd_hist": _to_float(latest.get("macd_hist"), 6),
            "rsi14": _to_float(latest.get("rsi14"), 4),
            "kd_k": _to_float(latest.get("kd_k"), 4),
            "kd_d": _to_float(latest.get("kd_d"), 4),
            "bb_mid": _to_float(latest.get("bb_mid"), 4),
            "bb_upper": _to_float(latest.get("bb_upper"), 4),
            "bb_lower": _to_float(latest.get("bb_lower"), 4),
            "bb_width": _to_float(latest.get("bb_width"), 6),
            "volume": _to_float(latest.get("volume"), 0),
            "volume_ma5": _to_float(latest.get("volume_ma5"), 0),
            "volume_ma20": _to_float(latest.get("volume_ma20"), 0),
            "relative_strength_20d": rs,
        }

        warnings: list[str] = []
        trading_days = int(len(price_df))
        if trading_days < 60:
            warnings.append("可用交易日少於 60，分析可信度下降")
        if benchmark_df.empty:
            warnings.append("基準資料不足，部分相對強弱判讀受限")

        payload = {
            "ok": True,
            "ticker": ticker,
            "resolved_symbol": resolved_symbol,
            "market": _normalize_market(market),
            "board": board,
            "analysis_date": analysis_date.isoformat(),
            "window": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "lookback_days": lookback_days,
            },
            "benchmark": {
                "symbol": bench_symbol,
                "rows": int(len(benchmark_df)),
            },
            "data_quality": {
                "trading_days": trading_days,
                "warnings": warnings,
            },
            "latest_metrics": latest_metrics,
            "signal_summary": signals,
            "price_tail": _to_records(price_df, limit=60),
            "benchmark_tail": _to_records(benchmark_df, limit=60),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "ticker": ticker,
                "date": date,
                "market": market,
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )


technical_analyst = Agent(
    model="gemini-2.5-flash",
    name="technical_analyst",
    description="技術分析師：使用 yfinance + ta 計算固定指標，輸出可核對數值的 technical_report。",
    tools=[get_technical_indicators],
    output_key="technical_report",
    instruction="""你是 AlphaCouncil 的技術分析師。

任務規則：
1) 先呼叫一次 `get_technical_indicators(ticker, date, market)`；若未提供 `date` 或 `market`，預設為今日（Asia/Taipei）與 `tw`。
2) 僅使用工具回傳資料撰寫報告，禁止捏造不存在的數值。
3) 若 `ok=false`，直接回報資料錯誤與可能原因，不要硬做結論。
4) 若 `data_quality.warnings` 非空，必須在風險提示段落完整揭露。
5) 職責邊界：只做技術面（價格、趨勢、動能、波動、量價、相對強弱），不得混入新聞、籌碼、基本面。

輸出格式（固定）：
### 技術分析師報告

**分析日期**：<analysis_date>
**標的**：<ticker / resolved_symbol>
**市場**：<market>
**基準**：<benchmark.symbol>

#### 摘要
- 3 條最重要訊號（優先引用 signal_summary）

#### 趨勢分析
- 引用 close、MA5、MA20、MA60 的確切數字

#### 動能分析
- 引用 MACD / Signal / Hist、RSI14、KD(K/D) 的確切數字

#### 波動與量價分析
- 引用 Bollinger（mid/upper/lower/width）與 volume/volume_ma5/volume_ma20

#### 相對強弱
- 引用 relative_strength_20d 的 stock_return、benchmark_return、spread

#### 風險提示
- 條列資料限制、訊號衝突或過熱/過冷風險

最後加註：本報告僅供研究，不構成投資建議。
""",
)
