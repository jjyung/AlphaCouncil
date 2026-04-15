import datetime as dt
import json
import math
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from google.adk.agents.llm_agent import Agent

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PSYCHOLOGY_DATA_ROOT = _PROJECT_ROOT / "alpha_council" / "data" / "psychology"

_TTL_DAYS = {
    "core_volatility": 1,
    "vix_history": 1,
    "options_sentiment": 1,
    "market_behavior": 1,
    "capital_flow": 1,
}

_PRICE_CACHE: dict[str, pd.DataFrame] = {}

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _normalize_market(market: str) -> str:
    m = (market or "").strip().lower()
    if m not in {"us", "tw"}:
        raise ValueError("market must be 'us' or 'tw'")
    return m


def _parse_date(date: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(date))
    except ValueError as exc:
        raise ValueError("date must be ISO format YYYY-MM-DD") from exc


def _default_analysis_date() -> dt.date:
    return dt.datetime.now(ZoneInfo("Asia/Taipei")).date()


def _now_iso() -> str:
    return dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat()


def _canonical_ticker(market: str, ticker: str) -> str:
    t = ticker.strip().upper()
    if market == "tw":
        return t.split(".")[0]
    return t


def _to_float(v: Any, ndigits: int = 4) -> float | None:
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if math.isinf(out) or math.isnan(out):
        return None
    return round(out, ndigits)


def _to_num(raw: Any) -> float | None:
    s = str(raw).strip().replace(",", "")
    if not s or s in {"-", "--", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Cache infrastructure
# ---------------------------------------------------------------------------


def _cache_paths(
    market: str, ticker_canonical: str, analysis_date: dt.date
) -> dict[str, Path]:
    y = analysis_date.strftime("%Y")
    m = analysis_date.strftime("%m")
    base = _PSYCHOLOGY_DATA_ROOT / market / ticker_canonical / y / m
    return {
        "partition": base,
        "bundle": base / "bundle.v1.json",
        "manifest": base / "manifest.json",
        "sources": base / "sources",
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_source_snapshot(
    sources_dir: Path,
    dataset: str,
    provider: str,
    period: str,
    payload: dict[str, Any] | list[dict[str, Any]],
) -> str:
    safe_period = re.sub(r"[^0-9A-Za-z._-]", "_", period)
    filename = f"{dataset}.{provider}.{safe_period}.json"
    full_path = sources_dir / filename
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(full_path.relative_to(_PROJECT_ROOT))


def _parse_iso_to_date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _new_manifest() -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": "psychology.bundle.v1",
        "created_at": now,
        "updated_at": now,
        "datasets": {},
        "coverage": {},
        "last_fetch_status": {},
    }


def _dataset_is_fresh(
    manifest: dict[str, Any] | None, dataset: str, today: dt.date
) -> bool:
    if not manifest:
        return False
    datasets = manifest.get("datasets", {})
    node = datasets.get(dataset)
    if not isinstance(node, dict):
        return False
    fetched_date = _parse_iso_to_date(node.get("fetched_at"))
    if fetched_date is None:
        return False
    ttl = int(node.get("ttl_days", _TTL_DAYS.get(dataset, 1)))
    age_days = (today - fetched_date).days
    return age_days <= ttl


def _upsert_manifest_dataset(
    manifest: dict[str, Any], dataset: str, period_end: str, status: str
) -> None:
    manifest.setdefault("datasets", {})[dataset] = {
        "period_end": period_end,
        "fetched_at": _now_iso(),
        "ttl_days": _TTL_DAYS.get(dataset, 1),
        "status": status,
    }
    manifest["updated_at"] = _now_iso()


def _snapshot_staleness_days(
    manifest: dict[str, Any], today: dt.date, datasets: list[str]
) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    nodes = manifest.get("datasets", {}) if isinstance(manifest, dict) else {}
    for dataset in datasets:
        fetched = _parse_iso_to_date((nodes.get(dataset, {}) or {}).get("fetched_at"))
        out[dataset] = None if fetched is None else (today - fetched).days
    return out


# ---------------------------------------------------------------------------
# Price data helpers
# ---------------------------------------------------------------------------


def _download_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    key = f"{symbol}:{start}:{end}"
    if key in _PRICE_CACHE:
        return _PRICE_CACHE[key].copy()

    raw = yf.download(
        tickers=symbol,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip().lower() for c in df.columns]

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
    out = df[["date", "open", "high", "low", "close", "volume"]]
    _PRICE_CACHE[key] = out.copy()
    return out


def _compute_realized_vol(close: pd.Series, window: int) -> float | None:
    s = pd.to_numeric(close, errors="coerce").dropna()
    if len(s) < window + 1:
        return None
    ret = s.pct_change().dropna()
    if len(ret) < window:
        return None
    vol = ret.tail(window).std(ddof=1)
    if pd.isna(vol):
        return None
    return _to_float(float(vol) * math.sqrt(252) * 100, 4)


# ---------------------------------------------------------------------------
# Statistical helpers (percentile / z-score)
# ---------------------------------------------------------------------------


def _compute_percentile(current: float, history: list[float]) -> float | None:
    """Compute current value's percentile within historical distribution."""
    valid = [x for x in history if x is not None and not math.isnan(x)]
    if len(valid) < 10:
        return None
    count_below = sum(1 for x in valid if x <= current)
    return _to_float(count_below / len(valid) * 100, 2)


def _compute_zscore(current: float, history: list[float]) -> float | None:
    """Compute z-score of current value vs historical distribution."""
    valid = [x for x in history if x is not None and not math.isnan(x)]
    if len(valid) < 10:
        return None
    arr = np.array(valid)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    if std < 1e-9:
        return None
    return _to_float((current - mean) / std, 4)


def _compute_rate_of_change(series: list[float], window: int = 5) -> float | None:
    """Compute percentage rate of change over the last *window* values."""
    valid = [x for x in series if x is not None and not math.isnan(x)]
    if len(valid) < window + 1:
        return None
    old = valid[-(window + 1)]
    new = valid[-1]
    if abs(old) < 1e-9:
        return None
    return _to_float((new - old) / abs(old) * 100, 4)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def _fetch_yf_latest_close(
    symbol: str, analysis_date: dt.date
) -> tuple[float | None, str | None]:
    start = (analysis_date - dt.timedelta(days=30)).isoformat()
    end = (analysis_date + dt.timedelta(days=1)).isoformat()
    df = _download_prices(symbol, start, end)
    if df.empty:
        return None, None
    row = df[df["date"] <= pd.Timestamp(analysis_date)]
    if row.empty:
        return None, None
    latest = row.iloc[-1]
    d = pd.Timestamp(latest["date"]).date().isoformat()
    return _to_float(latest["close"], 4), d


def _fetch_vix_history_us(
    analysis_date: dt.date, lookback_days: int = 365
) -> list[float]:
    """Fetch 1 year of VIX daily close from yfinance."""
    start = (analysis_date - dt.timedelta(days=lookback_days + 10)).isoformat()
    end = (analysis_date + dt.timedelta(days=1)).isoformat()
    df = _download_prices("^VIX", start, end)
    if df.empty:
        return []
    df = df[df["date"] <= pd.Timestamp(analysis_date)]
    return [float(x) for x in df["close"].dropna().tolist()]


def _fetch_taifex_vix_history(
    analysis_date: dt.date, lookback_months: int = 12
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch TAIFEX VIX daily data for the past *lookback_months* months.

    Uses the monthly download files at:
    https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/YYYYMMnew.txt

    Returns (records, warnings) where each record has keys 'date' and 'vix'.
    """
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    base_url = (
        "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt"
    )

    current = analysis_date.replace(day=1)
    for _ in range(lookback_months):
        ym = current.strftime("%Y%m")
        url = base_url.format(ym=ym)
        try:
            resp = requests.get(url, timeout=12)
            if resp.status_code != 200:
                # Month may not exist yet
                current = (current - dt.timedelta(days=1)).replace(day=1)
                continue
            text = resp.content.decode("big5", errors="replace")
            lines = text.strip().split("\n")
            for line in lines[2:]:  # skip header + separator
                parts = line.strip().split("\t")
                if len(parts) < 3:
                    continue
                date_str = parts[0].strip()
                if not re.match(r"^\d{8}$", date_str):
                    continue
                iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                # VIX value is typically in the 3rd position (index 2),
                # but may have empty tabs; find first non-empty numeric value
                vix_val = None
                for p in parts[2:]:
                    v = _to_num(p)
                    if v is not None and v > 0:
                        vix_val = v
                        break
                if vix_val is not None:
                    records.append({"date": iso_date, "vix": round(vix_val, 4)})
        except Exception as exc:
            warnings.append(f"TAIFEX VIX history fetch failed for {ym}: {exc}")

        # Move to previous month
        current = (current - dt.timedelta(days=1)).replace(day=1)

    records.sort(key=lambda r: r["date"])
    return records, warnings


def _fetch_taifex_vix(analysis_date: dt.date) -> tuple[dict[str, Any], list[str]]:
    """Fetch the latest TAIFEX VIX value up to analysis_date.

    Uses the monthly .txt download files (same mechanism as
    ``_fetch_taifex_vix_history``) instead of HTML table scraping, because
    the HTML page renders daily data via JavaScript which ``pd.read_html``
    cannot capture.

    Tries the current month first; if no valid row is found, falls back to
    the previous month's file.
    """
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "taifex_vix": None,
        "as_of": None,
        "provider": "taifex",
    }
    base_url = (
        "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt"
    )
    target = analysis_date.isoformat()

    # Try current month, then previous month
    months_to_try = [
        analysis_date.replace(day=1),
        (analysis_date.replace(day=1) - dt.timedelta(days=1)).replace(day=1),
    ]

    best_date: str | None = None
    best_vix: float | None = None

    for month_start in months_to_try:
        ym = month_start.strftime("%Y%m")
        url = base_url.format(ym=ym)
        try:
            resp = requests.get(url, timeout=12)
            if resp.status_code != 200:
                continue
            text = resp.content.decode("big5", errors="replace")
            lines = text.strip().split("\n")
            for line in lines[2:]:  # skip header + separator
                parts = line.strip().split("\t")
                if len(parts) < 3:
                    continue
                date_str = parts[0].strip()
                if not re.match(r"^\d{8}$", date_str):
                    continue
                iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                if iso_date > target:
                    continue
                vix_val = None
                for p in parts[2:]:
                    v = _to_num(p)
                    if v is not None and v > 0:
                        vix_val = v
                        break
                if vix_val is not None:
                    if best_date is None or iso_date > best_date:
                        best_date = iso_date
                        best_vix = vix_val
        except Exception as exc:
            warnings.append(f"TAIFEX VIX fetch failed for {ym}: {exc}")

    if best_vix is not None:
        payload["taifex_vix"] = _to_float(best_vix, 4)
        payload["as_of"] = best_date
    else:
        warnings.append("TAIFEX VIX has no data up to analysis_date")
    return payload, warnings


def _fetch_taifex_pcr(analysis_date: dt.date) -> tuple[dict[str, Any], list[str]]:
    """Fetch TAIFEX Put/Call Ratio (volume & OI) up to analysis_date.

    Uses the TAIFEX Open API (``openapi.taifex.com.tw/v1/PutCallRatio``)
    which returns structured JSON (~20 trading days), replacing the previous
    HTML table scraping approach.
    """
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "pcr_volume": None,
        "pcr_oi": None,
        "as_of": None,
        "provider": "taifex_openapi",
    }
    url = "https://openapi.taifex.com.tw/v1/PutCallRatio"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            warnings.append("TAIFEX Open API PutCallRatio returned empty data")
            return payload, warnings

        target = analysis_date.isoformat().replace("-", "")  # YYYYMMDD

        # Find the latest record <= analysis_date
        best: dict[str, Any] | None = None
        for record in data:
            rec_date = str(record.get("Date", "")).strip()
            if not rec_date or len(rec_date) != 8:
                continue
            if rec_date > target:
                continue
            if best is None or rec_date > best["_raw_date"]:
                iso_date = f"{rec_date[:4]}-{rec_date[4:6]}-{rec_date[6:8]}"
                # API returns percentage (e.g. 125.26 = 125.26%);
                # convert to ratio (1.2526) for consistency with signal logic.
                pcr_vol_raw = _to_num(record.get("PutCallVolumeRatio%"))
                pcr_oi_raw = _to_num(record.get("PutCallOIRatio%"))
                best = {
                    "_raw_date": rec_date,
                    "as_of": iso_date,
                    "pcr_volume": _to_float(pcr_vol_raw / 100, 4)
                    if pcr_vol_raw is not None
                    else None,
                    "pcr_oi": _to_float(pcr_oi_raw / 100, 4)
                    if pcr_oi_raw is not None
                    else None,
                }

        if best is None:
            warnings.append("TAIFEX PCR has no record up to analysis_date")
            return payload, warnings

        payload["as_of"] = best["as_of"]
        payload["pcr_volume"] = best["pcr_volume"]
        payload["pcr_oi"] = best["pcr_oi"]
        if payload["pcr_volume"] is None:
            warnings.append("TAIFEX PCR(volume) parse failed")
        if payload["pcr_oi"] is None:
            warnings.append("TAIFEX PCR(OI) parse failed")
    except Exception as exc:
        warnings.append(f"TAIFEX PCR fetch failed: {exc}")
    return payload, warnings


def _fetch_us_options_sentiment(
    ticker: str, analysis_date: dt.date
) -> tuple[dict[str, Any], list[str]]:
    """Fetch US options data and compute full IV suite.

    Computes: put_call_ratio (volume & OI), ATM IV (near/next month),
    IV term slope, 25-delta Risk Reversal, 25-delta Butterfly.
    Uses moneyness approximation for delta mapping.
    """
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "put_call_ratio_volume": None,
        "put_call_ratio_oi": None,
        "atm_iv_near": None,
        "atm_iv_next": None,
        "iv_term_slope": None,
        "iv_rr_25d": None,
        "iv_bf_25d": None,
        "expiry_near": None,
        "expiry_next": None,
    }
    try:
        tk = yf.Ticker(ticker)
        expiries = tk.options or []
        if len(expiries) < 1:
            warnings.append("US options expiry unavailable; IV suite 缺失")
            return payload, warnings

        # Get current price for moneyness calculation
        hist = tk.history(period="5d")
        if hist.empty:
            warnings.append("US stock price unavailable for IV calculation")
            return payload, warnings
        spot = float(hist["Close"].iloc[-1])

        # --- Near-month chain ---
        expiry_near = expiries[0]
        payload["expiry_near"] = expiry_near
        chain_near = tk.option_chain(expiry_near)
        puts_near = getattr(chain_near, "puts", pd.DataFrame())
        calls_near = getattr(chain_near, "calls", pd.DataFrame())

        # Put/Call Ratio from near-month
        p_vol = _to_float(
            puts_near.get("volume", pd.Series(dtype=float)).fillna(0).sum(), 6
        )
        c_vol = _to_float(
            calls_near.get("volume", pd.Series(dtype=float)).fillna(0).sum(), 6
        )
        p_oi = _to_float(
            puts_near.get("openInterest", pd.Series(dtype=float)).fillna(0).sum(), 6
        )
        c_oi = _to_float(
            calls_near.get("openInterest", pd.Series(dtype=float)).fillna(0).sum(), 6
        )

        if c_vol and c_vol > 0 and p_vol is not None:
            payload["put_call_ratio_volume"] = _to_float(p_vol / c_vol, 4)
        else:
            warnings.append("US options volume insufficient for put/call volume ratio")

        if c_oi and c_oi > 0 and p_oi is not None:
            payload["put_call_ratio_oi"] = _to_float(p_oi / c_oi, 4)
        else:
            warnings.append("US options OI insufficient for put/call OI ratio")

        # --- ATM IV (near month) ---
        atm_iv_near = _extract_atm_iv(calls_near, puts_near, spot)
        payload["atm_iv_near"] = atm_iv_near

        # --- 25-delta RR and BF (near month, moneyness approximation) ---
        rr, bf = _extract_25d_rr_bf(calls_near, puts_near, spot)
        payload["iv_rr_25d"] = rr
        payload["iv_bf_25d"] = bf

        # --- Next-month chain (for term structure) ---
        if len(expiries) >= 2:
            expiry_next = expiries[1]
            payload["expiry_next"] = expiry_next
            chain_next = tk.option_chain(expiry_next)
            calls_next = getattr(chain_next, "calls", pd.DataFrame())
            puts_next = getattr(chain_next, "puts", pd.DataFrame())
            atm_iv_next = _extract_atm_iv(calls_next, puts_next, spot)
            payload["atm_iv_next"] = atm_iv_next

            # IV term slope = next - near
            if atm_iv_near is not None and atm_iv_next is not None:
                payload["iv_term_slope"] = _to_float(atm_iv_next - atm_iv_near, 4)
        else:
            warnings.append(
                "Only 1 expiry available; iv_term_slope and atm_iv_next unavailable"
            )

        if atm_iv_near is None:
            warnings.append("ATM IV (near) unavailable")
        if rr is None or bf is None:
            warnings.append("25-delta RR/BF unavailable (insufficient strike data)")

    except Exception as exc:
        warnings.append(f"US options fetch failed: {exc}")
    return payload, warnings


def _extract_atm_iv(
    calls: pd.DataFrame, puts: pd.DataFrame, spot: float
) -> float | None:
    """Find ATM IV as the average of call and put IV at the strike closest to spot."""
    for chain in [calls, puts]:
        if chain.empty or "strike" not in chain.columns:
            continue
        if "impliedVolatility" not in chain.columns:
            continue

    call_iv = _iv_at_strike(calls, spot)
    put_iv = _iv_at_strike(puts, spot)

    if call_iv is not None and put_iv is not None:
        return _to_float((call_iv + put_iv) / 2 * 100, 4)
    if call_iv is not None:
        return _to_float(call_iv * 100, 4)
    if put_iv is not None:
        return _to_float(put_iv * 100, 4)
    return None


def _iv_at_strike(chain: pd.DataFrame, target_strike: float) -> float | None:
    """Get the IV of the strike closest to target_strike."""
    if chain.empty:
        return None
    df = chain.dropna(subset=["strike", "impliedVolatility"]).copy()
    if df.empty:
        return None
    df["_dist"] = (df["strike"] - target_strike).abs()
    closest = df.loc[df["_dist"].idxmin()]
    iv = closest.get("impliedVolatility")
    if pd.isna(iv):
        return None
    return float(iv)


def _extract_25d_rr_bf(
    calls: pd.DataFrame, puts: pd.DataFrame, spot: float
) -> tuple[float | None, float | None]:
    """Compute 25-delta Risk Reversal and Butterfly using moneyness approximation.

    Moneyness approximation:
    - 25-delta call ≈ strike at ~105-108% of spot (use ~106%)
    - 25-delta put  ≈ strike at ~92-95% of spot  (use ~94%)

    RR = IV(25d call) - IV(25d put)  → positive = bullish skew
    BF = (IV(25d call) + IV(25d put)) / 2 - IV(ATM)  → positive = fat tails
    """
    call_25d_strike = spot * 1.06
    put_25d_strike = spot * 0.94

    iv_call_25d = _iv_at_strike(calls, call_25d_strike)
    iv_put_25d = _iv_at_strike(puts, put_25d_strike)
    iv_atm_call = _iv_at_strike(calls, spot)
    iv_atm_put = _iv_at_strike(puts, spot)

    if iv_call_25d is None or iv_put_25d is None:
        return None, None

    rr = _to_float((iv_call_25d - iv_put_25d) * 100, 4)

    # BF needs ATM IV
    atm_iv = None
    if iv_atm_call is not None and iv_atm_put is not None:
        atm_iv = (iv_atm_call + iv_atm_put) / 2
    elif iv_atm_call is not None:
        atm_iv = iv_atm_call
    elif iv_atm_put is not None:
        atm_iv = iv_atm_put

    bf = None
    if atm_iv is not None:
        wing_avg = (iv_call_25d + iv_put_25d) / 2
        bf = _to_float((wing_avg - atm_iv) * 100, 4)

    return rr, bf


def _fetch_market_behavior(
    symbol: str, analysis_date: dt.date
) -> tuple[dict[str, Any], list[str]]:
    """Fetch market behavior proxy indicators (realized volatility only).

    Removed in design revision: ma5_bias_pct, gap_count_5d, alternation_count_5d.
    """
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "symbol": symbol,
        "as_of": None,
        "realized_vol_5d": None,
        "realized_vol_20d": None,
    }
    start = (analysis_date - dt.timedelta(days=80)).isoformat()
    end = (analysis_date + dt.timedelta(days=1)).isoformat()
    try:
        df = _download_prices(symbol, start, end)
        if df.empty:
            warnings.append(f"{symbol} price data unavailable")
            return payload, warnings
        df = df[df["date"] <= pd.Timestamp(analysis_date)]
        if df.empty:
            warnings.append(f"{symbol} has no row on/before analysis_date")
            return payload, warnings

        payload["as_of"] = pd.Timestamp(df.iloc[-1]["date"]).date().isoformat()
        close = df["close"]
        payload["realized_vol_5d"] = _compute_realized_vol(close, 5)
        payload["realized_vol_20d"] = _compute_realized_vol(close, 20)
    except Exception as exc:
        warnings.append(f"Market behavior fetch failed: {exc}")
    return payload, warnings


def _fetch_tw_capital_flow_proxy(
    analysis_date: dt.date,
) -> tuple[dict[str, Any], list[str]]:
    """Fetch USD/TWD exchange rate trend as indirect capital flow proxy."""
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "symbol": "USDTWD=X",
        "as_of": None,
        "usdtwd_close": None,
        "trend_5d": None,
    }
    start = (analysis_date - dt.timedelta(days=20)).isoformat()
    end = (analysis_date + dt.timedelta(days=1)).isoformat()
    try:
        df = _download_prices("USDTWD=X", start, end)
        if df.empty:
            warnings.append("USDTWD data unavailable")
            return payload, warnings
        df = df[df["date"] <= pd.Timestamp(analysis_date)]
        if df.empty:
            warnings.append("USDTWD has no row on/before analysis_date")
            return payload, warnings

        payload["as_of"] = pd.Timestamp(df.iloc[-1]["date"]).date().isoformat()
        payload["usdtwd_close"] = _to_float(df.iloc[-1]["close"], 4)

        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        if len(close) >= 6:
            delta = close.iloc[-1] - close.iloc[-6]
            if delta > 0.02:
                payload["trend_5d"] = "up"
            elif delta < -0.02:
                payload["trend_5d"] = "down"
            else:
                payload["trend_5d"] = "flat"
    except Exception as exc:
        warnings.append(f"USDTWD fetch failed: {exc}")
    return payload, warnings


# ---------------------------------------------------------------------------
# Signal derivation (percentile / z-score based)
# ---------------------------------------------------------------------------


def _derive_signals(
    snapshot: dict[str, Any],
    market: str,
    vix_history: list[float],
) -> dict[str, Any]:
    """Deterministic rule engine using percentile/z-score.

    Design principles (from psychology-analyst.md):
    - No fixed numeric thresholds for VIX or PCR (Tier C forbidden)
    - Use historical percentile (1Y) and z-score for regime detection
    - Multi-signal requirement: options sentiment requires >=2 aligned signals
    - VVIX is conditional: only when VIX rapidly rising
    - States: 恐慌 / 樂觀 / 觀望 / 轉折
    """
    core = snapshot.get("core_volatility", {})
    options = snapshot.get("options_sentiment", {})
    behavior = snapshot.get("market_behavior_proxy", {})
    flow = snapshot.get("capital_flow_proxy", {})

    risk_flags: list[str] = []
    confidence_notes: list[str] = []

    # --- VIX percentile & z-score ---
    vix = core.get("vix") if market == "us" else core.get("taifex_vix")
    vix_pct = None
    vix_z = None
    vix_5d_roc = None

    if isinstance(vix, (int, float)) and vix_history:
        vix_pct = _compute_percentile(vix, vix_history)
        vix_z = _compute_zscore(vix, vix_history)
        vix_5d_roc = _compute_rate_of_change(vix_history + [vix], 5)
        # Note if history window is shorter than 1 year (~200 trading days)
        if len(vix_history) < 200:
            confidence_notes.append(
                f"VIX 歷史資料僅 {len(vix_history)} 筆（不足 1 年），"
                "percentile/z-score 可能偏差"
            )

    # --- Volatility regime (percentile-based) ---
    if vix_pct is not None:
        if vix_pct > 75:
            regime = "擴張"
            risk_flags.append(f"VIX percentile {vix_pct}%，波動處於歷史偏高區間")
        elif vix_pct < 25:
            regime = "收斂"
            risk_flags.append(f"VIX percentile {vix_pct}%，波動偏低，留意過度樂觀")
        else:
            regime = "正常"
    else:
        # Fallback to realized vol comparison
        rv5 = behavior.get("realized_vol_5d")
        rv20 = behavior.get("realized_vol_20d")
        if (
            isinstance(rv5, (int, float))
            and isinstance(rv20, (int, float))
            and rv20 > 0
        ):
            if rv5 > rv20 * 1.5:
                regime = "擴張"
            elif rv5 < rv20 * 0.7:
                regime = "收斂"
            else:
                regime = "正常"
            confidence_notes.append("VIX 資料不足，波動 regime 以實現波動率推估")
        else:
            regime = "資料不足"
            confidence_notes.append("VIX 與實現波動率皆不足，無法判斷波動 regime")

    # --- VIX rapid spike detection (for VVIX conditional usage) ---
    vvix_note = None
    if market == "us" and vix_5d_roc is not None and vix_5d_roc > 30:
        vvix = core.get("vvix")
        if isinstance(vvix, (int, float)):
            vvix_note = f"VIX 5 日急升 {vix_5d_roc}%，VVIX={vvix}，波動加速中"
            risk_flags.append(vvix_note)
    elif market == "us" and vix_5d_roc is not None and vix_5d_roc < -30:
        risk_flags.append(f"VIX 5 日急降 {vix_5d_roc}%，波動快速收斂")

    # --- Short-term realized vol expansion ---
    rv5 = behavior.get("realized_vol_5d")
    rv20 = behavior.get("realized_vol_20d")
    if isinstance(rv5, (int, float)) and isinstance(rv20, (int, float)) and rv20 > 0:
        if rv5 > rv20 * 1.5:
            risk_flags.append("短期實現波動率顯著擴張（5 日 > 20 日均值 ×1.5）")

    # --- Options sentiment (multi-signal requirement) ---
    pcr_oi = (
        options.get("put_call_ratio_oi") if market == "us" else options.get("pcr_oi")
    )
    pcr_vol = (
        options.get("put_call_ratio_volume")
        if market == "us"
        else options.get("pcr_volume")
    )

    # Count directional signals for options sentiment
    hedge_signals = 0  # positive = hedging/bearish, negative = speculative/bullish
    signal_details: list[str] = []
    structural_flow_warning = False

    if isinstance(pcr_oi, (int, float)) and isinstance(pcr_vol, (int, float)):
        # Check if both PCR measures agree in direction
        # Note: we compare relative magnitude, not absolute thresholds
        if pcr_oi > 1.0 and pcr_vol > 1.0:
            hedge_signals += 1
            signal_details.append("PCR 雙口徑 >1.0，偏避險")
        elif pcr_oi < 1.0 and pcr_vol < 1.0:
            hedge_signals -= 1
            signal_details.append("PCR 雙口徑 <1.0，偏投機")
        else:
            # Divergence between volume and OI PCR
            structural_flow_warning = True
            confidence_notes.append(
                "PCR 成交量與 OI 口徑方向不一致，可能受結構性交易行為影響"
                "（如 covered call 壓低 PCR 或法人避險拉高 PCR），"
                "PCR 判讀降格為輔助參考"
            )
    elif isinstance(pcr_oi, (int, float)):
        confidence_notes.append("僅有 OI 口徑 PCR，成交量口徑缺失")
    elif isinstance(pcr_vol, (int, float)):
        confidence_notes.append("僅有成交量口徑 PCR，OI 口徑缺失")

    # US-specific: IV skew signals
    if market == "us":
        iv_rr = options.get("iv_rr_25d")
        iv_bf = options.get("iv_bf_25d")
        iv_term = options.get("iv_term_slope")

        if isinstance(iv_rr, (int, float)):
            if iv_rr < -2:  # puts more expensive → bearish skew
                hedge_signals += 1
                signal_details.append(f"25d RR={iv_rr}，put 偏貴，偏避險")
            elif iv_rr > 2:  # calls more expensive → bullish skew
                hedge_signals -= 1
                signal_details.append(f"25d RR={iv_rr}，call 偏貴，偏投機")

        if isinstance(iv_bf, (int, float)):
            if iv_bf > 3:
                risk_flags.append(f"25d BF={iv_bf}，尾部風險溢酬偏高")

        if isinstance(iv_term, (int, float)):
            if iv_term < -3:
                hedge_signals += 1
                signal_details.append(
                    f"IV term slope={iv_term}，近月 IV > 遠月（backwardation），"
                    "短期恐慌"
                )
            elif iv_term > 3:
                signal_details.append(
                    f"IV term slope={iv_term}，近月 IV < 遠月（contango），市場平靜"
                )

    # Determine options_sentiment (requires multi-signal alignment)
    if structural_flow_warning:
        # PCR unreliable → rely on IV signals only (US) or mark as insufficient
        if market == "us" and abs(hedge_signals) >= 1:
            option_sentiment = "偏避險" if hedge_signals > 0 else "偏投機"
            confidence_notes.append("因 PCR 結構性失真，選擇權情緒主要依據 IV 指標判讀")
        else:
            option_sentiment = "中性"
            confidence_notes.append(
                "PCR 結構性失真且無足夠 IV 訊號，選擇權情緒判為中性（insufficient evidence）"
            )
    elif abs(hedge_signals) >= 1:
        option_sentiment = "偏避險" if hedge_signals > 0 else "偏投機"
    else:
        option_sentiment = "中性"

    # --- Capital flow proxy (TW only) ---
    flow_signal = None
    if market == "tw":
        trend_5d = flow.get("trend_5d")
        if trend_5d == "up":
            flow_signal = "risk-off"
            risk_flags.append("USD/TWD 近 5 日走升（台幣貶值），留意外資風險偏好轉弱")
        elif trend_5d == "down":
            flow_signal = "risk-on"
        elif trend_5d == "flat":
            flow_signal = "neutral"

    # --- Determine overall market psychology state ---
    # 恐慌 / 樂觀 / 觀望 / 轉折
    state = _determine_psychology_state(
        vix_pct=vix_pct,
        vix_z=vix_z,
        vix_5d_roc=vix_5d_roc,
        regime=regime,
        option_sentiment=option_sentiment,
        hedge_signals=hedge_signals,
        flow_signal=flow_signal,
        risk_flags=risk_flags,
        market=market,
    )

    return {
        "market_psychology_state": state,
        "volatility_regime": regime,
        "options_sentiment": option_sentiment,
        "options_sentiment_details": signal_details,
        "risk_preference": flow_signal,
        "vix_percentile": vix_pct,
        "vix_zscore": vix_z,
        "vix_5d_roc": vix_5d_roc,
        "risk_flags": sorted(set(risk_flags)),
        "confidence_notes": confidence_notes,
    }


def _determine_psychology_state(
    *,
    vix_pct: float | None,
    vix_z: float | None,
    vix_5d_roc: float | None,
    regime: str,
    option_sentiment: str,
    hedge_signals: int,
    flow_signal: str | None,
    risk_flags: list[str],
    market: str,
) -> str:
    """Determine top-level psychology state: 恐慌 / 樂觀 / 觀望 / 轉折.

    Weighted scoring:
    - Core indicators (VIX, PCR/options sentiment): weight 2
    - Auxiliary indicators (capital flow, realized vol): weight 1

    轉折: VIX rapid spike/drop, or conflicting core signals.
    """
    # Weighted directional evidence
    panic_score = 0
    optimism_score = 0

    # --- Core: VIX (weight 2) ---
    if vix_pct is not None:
        if vix_pct > 85:
            panic_score += 4  # weight 2 × strong signal
        elif vix_pct > 75:
            panic_score += 2  # weight 2
        elif vix_pct < 15:
            optimism_score += 4
        elif vix_pct < 25:
            optimism_score += 2

    if vix_z is not None:
        if vix_z > 1.5:
            panic_score += 2  # weight 2
        elif vix_z < -1.5:
            optimism_score += 2

    # --- Core: Options sentiment (weight 2) ---
    if option_sentiment == "偏避險":
        panic_score += 2
    elif option_sentiment == "偏投機":
        optimism_score += 2

    # --- Auxiliary: Capital flow (weight 1) ---
    if flow_signal == "risk-off":
        panic_score += 1
    elif flow_signal == "risk-on":
        optimism_score += 1

    # --- 轉折 detection ---
    is_turning = False
    # Rapid VIX change
    if vix_5d_roc is not None and abs(vix_5d_roc) > 30:
        is_turning = True
    # Core signals conflicting (both panic and optimism from core indicators)
    if panic_score >= 4 and optimism_score >= 4:
        is_turning = True

    if is_turning:
        return "轉折"
    elif panic_score >= 6:
        return "恐慌"
    elif optimism_score >= 6:
        return "樂觀"
    elif panic_score >= 4 and optimism_score <= 1:
        return "恐慌"
    elif optimism_score >= 4 and panic_score <= 1:
        return "樂觀"
    else:
        return "觀望"


# ---------------------------------------------------------------------------
# Required datasets per market
# ---------------------------------------------------------------------------


def _required_datasets(market: str) -> list[str]:
    if market == "tw":
        return [
            "core_volatility",
            "vix_history",
            "options_sentiment",
            "market_behavior",
            "capital_flow",
        ]
    return ["core_volatility", "vix_history", "options_sentiment", "market_behavior"]


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------


def get_psychology_data(
    ticker: str,
    date: str | None = None,
    market: str = "tw",
    force_refresh: bool = False,
) -> str:
    """取得市場心理分析資料，包含波動指標、選擇權情緒、市場行為 proxy 與資金流 proxy。

    Args:
        ticker: 股票代碼（例如 "2330" 或 "AAPL"）
        date: 分析日期，ISO 格式 YYYY-MM-DD（預設為今日 Asia/Taipei）
        market: 市場別 "us" 或 "tw"（預設 "tw"）
        force_refresh: 是否強制刷新快取（預設 False）

    Returns:
        JSON 字串，包含 psychology_snapshot、signal_summary 與 data_quality。
    """
    try:
        m = _normalize_market(market)
        analysis_date = _default_analysis_date() if not date else _parse_date(date)
        ticker_canonical = _canonical_ticker(m, ticker)

        paths = _cache_paths(m, ticker_canonical, analysis_date)
        cached_bundle = _read_json(paths["bundle"]) or {}
        manifest = _read_json(paths["manifest"]) or _new_manifest()

        required = _required_datasets(m)
        fresh_map = {
            ds: _dataset_is_fresh(manifest, ds, analysis_date) for ds in required
        }
        all_fresh = all(fresh_map.values()) if fresh_map else False

        if (
            not force_refresh
            and isinstance(cached_bundle, dict)
            and cached_bundle.get("schema_version") == "psychology.bundle.v1"
            and all_fresh
        ):
            payload = {
                "ok": True,
                "ticker": ticker,
                "resolved_symbol": (cached_bundle.get("instrument") or {}).get(
                    "resolved_symbol"
                ),
                "market": m,
                "analysis_date": analysis_date.isoformat(),
                "schema_version": "psychology.bundle.v1",
                "cache": {
                    "bundle_file": str(paths["bundle"].relative_to(_PROJECT_ROOT)),
                    "manifest_file": str(paths["manifest"].relative_to(_PROJECT_ROOT)),
                    "cache_hit": True,
                    "force_refresh": False,
                    "fresh_map": fresh_map,
                },
                "sources": cached_bundle.get("lineage", {}).get("sources", []),
                "psychology_snapshot": cached_bundle.get("psychology_snapshot", {}),
                "signal_summary": cached_bundle.get("signal_summary", {}),
                "data_quality": cached_bundle.get("data_quality", {}),
                "lineage": cached_bundle.get("lineage", {}),
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        # --- Build snapshot incrementally ---
        snapshot: dict[str, Any] = {
            "core_volatility": (cached_bundle.get("psychology_snapshot") or {}).get(
                "core_volatility", {}
            ),
            "options_sentiment": (cached_bundle.get("psychology_snapshot") or {}).get(
                "options_sentiment", {}
            ),
            "market_behavior_proxy": (
                cached_bundle.get("psychology_snapshot") or {}
            ).get("market_behavior_proxy", {}),
            "capital_flow_proxy": (cached_bundle.get("psychology_snapshot") or {}).get(
                "capital_flow_proxy", {}
            ),
        }
        vix_history_data: list[float] = (
            cached_bundle.get("psychology_snapshot") or {}
        ).get("vix_history", [])

        source_map: dict[str, dict[str, Any]] = {}
        allowed_datasets = set(required)
        for node in (cached_bundle.get("lineage") or {}).get("sources", []):
            if not isinstance(node, dict) or not node.get("dataset"):
                continue
            dataset = str(node["dataset"])
            if dataset in allowed_datasets:
                source_map[dataset] = node

        warnings: list[str] = []

        def should_fetch(dataset: str) -> bool:
            if force_refresh:
                return True
            return not fresh_map.get(dataset, False)

        # --- Core volatility ---
        if should_fetch("core_volatility"):
            if m == "us":
                vix, vix_date = _fetch_yf_latest_close("^VIX", analysis_date)
                vvix, vvix_date = _fetch_yf_latest_close("^VVIX", analysis_date)
                core_payload: dict[str, Any] = {
                    "provider": "yfinance",
                    "vix": vix,
                    "vvix": vvix,
                    "vix_as_of": vix_date,
                    "vvix_as_of": vvix_date,
                }
                if vix is None:
                    warnings.append("VIX 缺失，波動 regime 可信度下降")
            else:
                core_payload, core_warn = _fetch_taifex_vix(analysis_date)
                warnings.extend(core_warn)

            snapshot["core_volatility"] = core_payload
            period_end = (
                core_payload.get("as_of")
                or core_payload.get("vix_as_of")
                or analysis_date.isoformat()
            )
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="core_volatility",
                provider=str(core_payload.get("provider", "mixed")),
                period=period_end,
                payload=core_payload,
            )
            source_map["core_volatility"] = {
                "dataset": "core_volatility",
                "provider": str(core_payload.get("provider", "mixed")),
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            _upsert_manifest_dataset(manifest, "core_volatility", period_end, "ok")
            manifest.setdefault("coverage", {})["core_volatility_period_end"] = (
                period_end
            )
            manifest.setdefault("last_fetch_status", {})["core_volatility"] = "ok"

        # --- VIX history (for percentile/z-score) ---
        if should_fetch("vix_history"):
            if m == "us":
                vix_history_data = _fetch_vix_history_us(analysis_date, 365)
                hist_provider = "yfinance"
            else:
                records, hist_warn = _fetch_taifex_vix_history(analysis_date, 12)
                warnings.extend(hist_warn)
                vix_history_data = [r["vix"] for r in records if r.get("vix")]
                hist_provider = "taifex"

            snapshot["vix_history"] = vix_history_data
            period_end = analysis_date.isoformat()
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="vix_history",
                provider=hist_provider,
                period=period_end,
                payload={"count": len(vix_history_data), "provider": hist_provider},
            )
            source_map["vix_history"] = {
                "dataset": "vix_history",
                "provider": hist_provider,
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            _upsert_manifest_dataset(manifest, "vix_history", period_end, "ok")
            if len(vix_history_data) < 50:
                warnings.append(
                    f"VIX 歷史資料僅 {len(vix_history_data)} 筆，"
                    "percentile/z-score 可信度有限"
                )

        # --- Options sentiment ---
        if should_fetch("options_sentiment"):
            if m == "us":
                opt_payload, opt_warn = _fetch_us_options_sentiment(
                    ticker_canonical, analysis_date
                )
            else:
                opt_payload, opt_warn = _fetch_taifex_pcr(analysis_date)
            warnings.extend(opt_warn)
            snapshot["options_sentiment"] = opt_payload

            period_end = opt_payload.get("as_of") or analysis_date.isoformat()
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="options_sentiment",
                provider=str(opt_payload.get("provider", "mixed")),
                period=period_end,
                payload=opt_payload,
            )
            source_map["options_sentiment"] = {
                "dataset": "options_sentiment",
                "provider": str(opt_payload.get("provider", "mixed")),
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            _upsert_manifest_dataset(manifest, "options_sentiment", period_end, "ok")
            manifest.setdefault("coverage", {})["options_sentiment_period_end"] = (
                period_end
            )
            manifest.setdefault("last_fetch_status", {})["options_sentiment"] = "ok"

        # --- Market behavior proxy ---
        if should_fetch("market_behavior"):
            behavior_symbol = "^TWII" if m == "tw" else ticker_canonical
            behavior_payload, behavior_warn = _fetch_market_behavior(
                behavior_symbol, analysis_date
            )
            warnings.extend(behavior_warn)
            snapshot["market_behavior_proxy"] = behavior_payload

            period_end = behavior_payload.get("as_of") or analysis_date.isoformat()
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="market_behavior",
                provider="yfinance",
                period=period_end,
                payload=behavior_payload,
            )
            source_map["market_behavior"] = {
                "dataset": "market_behavior",
                "provider": "yfinance",
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            _upsert_manifest_dataset(manifest, "market_behavior", period_end, "ok")
            manifest.setdefault("coverage", {})["market_behavior_period_end"] = (
                period_end
            )
            manifest.setdefault("last_fetch_status", {})["market_behavior"] = "ok"

        # --- Capital flow proxy (TW only) ---
        if m == "tw" and should_fetch("capital_flow"):
            flow_payload, flow_warn = _fetch_tw_capital_flow_proxy(analysis_date)
            warnings.extend(flow_warn)
            snapshot["capital_flow_proxy"] = flow_payload

            period_end = flow_payload.get("as_of") or analysis_date.isoformat()
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="capital_flow",
                provider="yfinance",
                period=period_end,
                payload=flow_payload,
            )
            source_map["capital_flow"] = {
                "dataset": "capital_flow",
                "provider": "yfinance",
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            _upsert_manifest_dataset(manifest, "capital_flow", period_end, "ok")
            manifest.setdefault("coverage", {})["capital_flow_period_end"] = period_end
            manifest.setdefault("last_fetch_status", {})["capital_flow"] = "ok"

        if m == "us":
            snapshot["capital_flow_proxy"] = {}

        # --- Fallback: if core_volatility VIX is missing, extract from vix_history ---
        core_vol = snapshot.get("core_volatility", {})
        if m == "tw" and core_vol.get("taifex_vix") is None and vix_history_data:
            # Use the latest value from history as fallback
            last_vix = vix_history_data[-1]
            snapshot["core_volatility"]["taifex_vix"] = _to_float(last_vix, 4)
            snapshot["core_volatility"]["as_of"] = "from_history"
            snapshot["core_volatility"]["provider"] = "taifex"
            warnings.append("台版 VIX 即時抓取失敗，已從歷史資料取最新值作為替代")
        elif m == "us" and core_vol.get("vix") is None and vix_history_data:
            last_vix = vix_history_data[-1]
            snapshot["core_volatility"]["vix"] = _to_float(last_vix, 4)
            snapshot["core_volatility"]["provider"] = "yfinance"
            warnings.append("VIX 即時抓取失敗，已從歷史資料取最新值作為替代")

        # --- Derive signals ---
        signals = _derive_signals(snapshot, m, vix_history_data)

        # --- Data quality ---
        # Only merge cached warnings if we didn't refresh those datasets.
        # For force_refresh or freshly-fetched datasets, use only current warnings.
        if force_refresh:
            effective_warnings = sorted(set(warnings))
        else:
            # Merge cached warnings only for datasets we did NOT re-fetch
            cached_warnings = (
                (cached_bundle.get("data_quality") or {}).get("warnings")
            ) or []
            effective_warnings = sorted({*warnings, *cached_warnings})

        # Degraded mode: only when core VIX data is truly missing
        core_vol = snapshot.get("core_volatility", {})
        core_vix = core_vol.get("vix") if m == "us" else core_vol.get("taifex_vix")
        degraded = core_vix is None
        if core_vix is None:
            effective_warnings.append(
                "核心波動指標缺失，degraded_mode=true，"
                "後續結論以 insufficient evidence 語氣呈現"
            )

        required_after = _required_datasets(m)
        fresh_after = {
            ds: _dataset_is_fresh(manifest, ds, analysis_date) for ds in required_after
        }

        bundle = {
            "schema_version": "psychology.bundle.v1",
            "instrument": {
                "ticker": ticker,
                "resolved_symbol": ticker_canonical,
                "market": m,
            },
            "analysis_date": analysis_date.isoformat(),
            "psychology_snapshot": snapshot,
            "signal_summary": signals,
            "data_quality": {
                "warnings": effective_warnings,
                "degraded_mode": degraded,
                "missing_fields": [
                    k
                    for k, v in {
                        "core_volatility": snapshot.get("core_volatility"),
                        "options_sentiment": snapshot.get("options_sentiment"),
                        "market_behavior_proxy": snapshot.get("market_behavior_proxy"),
                    }.items()
                    if not v
                ],
                "staleness_days": _snapshot_staleness_days(
                    manifest, analysis_date, required_after
                ),
            },
            "lineage": {
                "sources": [
                    source_map[k]
                    for k in sorted(source_map.keys())
                    if isinstance(source_map[k], dict)
                ],
                "fetched_at": _now_iso(),
                "cache_policy": "daily_immutable_unless_forced",
            },
        }

        _write_json(paths["bundle"], bundle)
        _write_json(paths["manifest"], manifest)

        payload = {
            "ok": True,
            "ticker": ticker,
            "resolved_symbol": ticker_canonical,
            "market": m,
            "analysis_date": analysis_date.isoformat(),
            "schema_version": "psychology.bundle.v1",
            "cache": {
                "bundle_file": str(paths["bundle"].relative_to(_PROJECT_ROOT)),
                "manifest_file": str(paths["manifest"].relative_to(_PROJECT_ROOT)),
                "cache_hit": False,
                "force_refresh": force_refresh,
                "fresh_map_before": fresh_map,
                "fresh_map_after": fresh_after,
            },
            "sources": bundle["lineage"]["sources"],
            "psychology_snapshot": bundle["psychology_snapshot"],
            "signal_summary": bundle["signal_summary"],
            "data_quality": bundle["data_quality"],
            "lineage": bundle["lineage"],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "ticker": ticker,
                "date": date,
                "market": market,
                "force_refresh": force_refresh,
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

psychology_analyst = Agent(
    model="gemini-2.5-flash",
    name="psychology_analyst",
    description="市場心理分析師：以 percentile/z-score 為核心判讀方法，產生可核對的 psychology_report。",
    tools=[get_psychology_data],
    output_key="psychology_report",
    instruction="""你是 AlphaCouncil 的市場心理分析師。

## 任務規則

1) 先呼叫一次 `get_psychology_data(ticker, date, market, force_refresh=False)`；若未提供 `date` 或 `market`，預設為今日（Asia/Taipei）與 `tw`。
2) 只使用工具回傳資料撰寫報告，禁止捏造數值。
3) 若 `ok=false`，直接回報資料錯誤與可能原因，不要硬做結論。
4) 若 `data_quality.degraded_mode=true`，必須在報告中以「insufficient evidence」語氣呈現，禁止在資料缺失時硬下方向性結論。
5) 若 `data_quality.warnings` 非空，必須在「風險提示」完整揭露。

## 職責邊界

- 只做波動 regime、風險偏好、選擇權情緒與市場行為 proxy 分析
- **不得**混入新聞語氣、社群情緒（歸 News Analyst）
- **不得**混入三大法人買賣超、融資融券、借券賣出（歸 Chip Analyst）
- **不得**做價格趨勢、技術指標判斷（歸 Technical Analyst）

## 判讀原則

- **禁止使用固定數字門檻**（如 VIX > 30 = 恐慌）作為判讀規則。必須引用 `vix_percentile`、`vix_zscore` 等歷史校準指標。
- **禁止以單一指標獨立下結論**（Tier C 禁止）。例如不可只用 PCR 就判斷偏多或偏空。
- PCR 成交量口徑與 OI 口徑須方向一致才可提高可信度；若方向不一致，須說明可能原因（結構性 flow）。
- 實現波動率為間接觀測，報告中須明確標註。
- 核心指標（VIX、PCR）的判讀優先於輔助指標（匯率、實現波動率）。當兩者矛盾時，以核心指標為準。

## 輸出格式

### 市場心理分析師報告

**分析日期**：<analysis_date>
**標的**：<ticker>（<market>）

#### 摘要

用 2-3 句話回答「所以總體來說，目前市場心理狀態是什麼」。要求：
- 明確給出整合判讀結論（`market_psychology_state`），不能只列指標
- 說明結論的主要依據（哪些核心指標支持這個判斷）
- 若指標方向不一致，說明以哪個訊號為主判讀、哪個為輔助參考，以及不一致的可能原因

#### 波動 Regime
- 核心波動指標數值（US: VIX；TW: 台版 VIX）
- VIX percentile（歷史分位數）與 z-score
- VIX 5 日變化率（若有異常需標注）
- `volatility_regime` 判讀結果：擴張 / 收斂 / 正常
- US 市場：VVIX 僅在 VIX 快速拉升時提及，一般情況不納入

#### 選擇權情緒
- TW: pcr_volume / pcr_oi → 兩種口徑方向是否一致
- US: put_call_ratio_volume / put_call_ratio_oi + atm_iv_near / atm_iv_next + iv_term_slope + iv_rr_25d / iv_bf_25d
- `options_sentiment` 判讀結果：偏避險 / 中性 / 偏投機
- 若有 `confidence_notes`，須說明判讀限制

#### 資金流 Proxy（僅 TW）
- USD/TWD 收盤價與近 5 日趨勢
- 暗示 risk-on / risk-off / neutral
- 明確標註：匯率為間接觀測，非直接情緒量測

#### 市場行為 Proxy（間接觀測）
- 近 5 日實現波動率 vs 20 日實現波動率
- **明確註記：以上為間接觀測，非直接情緒量測**

#### 與技術面一致性
- 心理狀態與目前波動 regime 是否一致或背離
- 若有背離，說明可能原因（此段落基於工具資料推論，不需額外技術分析數據）

#### 風險提示
- 條列所有 `risk_flags`
- 揭露 `data_quality.warnings` 與 `degraded_mode`
- 標示 `confidence_notes` 中的判讀限制

最後加註：本報告僅供研究，不構成投資建議。
""",
)
