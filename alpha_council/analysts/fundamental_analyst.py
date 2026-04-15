import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from google.adk.agents.llm_agent import Agent

_TWSE_BWIBBU_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
_TPEX_PE_PB_YIELD_CANDIDATES = [
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
    "https://www.tpex.org.tw/openapi/v1/tpex_esb_peratio_analysis",
]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FUNDAMENTALS_DATA_ROOT = _PROJECT_ROOT / "alpha_council" / "data" / "fundamentals"

_TTL_DAYS = {
    "valuation_snapshot": 1,
    "monthly_revenue": 35,
    "quarterly_financials": 100,
}


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


def _cache_paths(
    market: str, ticker_canonical: str, analysis_date: dt.date
) -> dict[str, Path]:
    y = analysis_date.strftime("%Y")
    m = analysis_date.strftime("%m")
    base = _FUNDAMENTALS_DATA_ROOT / market / ticker_canonical / y / m
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


def _new_manifest() -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": "fundamentals.bundle.v1",
        "created_at": now,
        "updated_at": now,
        "datasets": {},
        "coverage": {},
        "last_fetch_status": {},
    }


def _upsert_manifest_dataset(
    manifest: dict[str, Any],
    dataset: str,
    period_end: str,
    status: str,
) -> None:
    manifest.setdefault("datasets", {})[dataset] = {
        "period_end": period_end,
        "fetched_at": _now_iso(),
        "ttl_days": _TTL_DAYS.get(dataset, 1),
        "status": status,
    }
    manifest["updated_at"] = _now_iso()


def _snapshot_staleness_days(
    manifest: dict[str, Any], today: dt.date
) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    datasets = manifest.get("datasets", {}) if isinstance(manifest, dict) else {}
    for dataset in _TTL_DAYS:
        fetched = _parse_iso_to_date(
            (datasets.get(dataset, {}) or {}).get("fetched_at")
        )
        out[dataset] = None if fetched is None else (today - fetched).days
    return out


def _to_float(v: Any, ndigits: int = 4) -> float | None:
    if v is None:
        return None
    if isinstance(v, str):
        parsed = _parse_numeric(v)
        if parsed is None:
            return None
        return round(parsed, ndigits)
    try:
        if pd.isna(v):
            return None
    except TypeError:
        pass
    try:
        return round(float(v), ndigits)
    except (TypeError, ValueError):
        return None


def _parse_numeric(raw: str) -> float | None:
    text = str(raw).strip()
    if not text:
        return None
    if text in {"-", "--", "N/A", "NA", "nan", "None"}:
        return None
    cleaned = text.replace(",", "")
    cleaned = cleaned.replace("％", "%")
    cleaned = re.sub(r"[^0-9.+\-%]", "", cleaned)
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    if cleaned in {"", "+", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _normalize_dividend_yield_pct(info: dict[str, Any]) -> float | None:
    raw = _to_float(info.get("dividendYield"), ndigits=6)
    if raw is None:
        return None

    annual_div = _to_float(info.get("trailingAnnualDividendRate"), ndigits=6)
    price = _to_float(info.get("currentPrice"), ndigits=6)
    if annual_div is not None and price is not None and price > 0:
        calc_pct = _to_float((annual_div / price) * 100, ndigits=4)
        if calc_pct is not None:
            if abs(raw - calc_pct) <= 0.2:
                return _to_float(raw, ndigits=2)
            if abs((raw * 100) - calc_pct) <= 0.2:
                return _to_float(raw * 100, ndigits=2)

    if 0 <= raw <= 0.2:
        return _to_float(raw * 100, ndigits=2)
    return _to_float(raw, ndigits=2)


def _extract_board_from_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if s.endswith(".TWO"):
        return "otc"
    if s.endswith(".TW"):
        return "listed"
    return "unknown"


def _tw_symbol_candidates(ticker: str) -> list[str]:
    t = ticker.strip().upper()
    if t.endswith(".TW") or t.endswith(".TWO"):
        return [t]
    if t.isdigit():
        return [f"{t}.TW", f"{t}.TWO"]
    return [t]


def _resolve_tw_board_from_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if t.endswith(".TW"):
        return "listed"
    if t.endswith(".TWO"):
        return "otc"
    return "unknown"


def _normalize_index_label(s: Any) -> str:
    return re.sub(r"\s+", "", str(s).strip().lower())


def _row_value(
    df: pd.DataFrame | None,
    aliases: list[str],
    col_pos: int = 0,
    ndigits: int = 4,
) -> float | None:
    if df is None or df.empty:
        return None
    if col_pos < 0 or col_pos >= len(df.columns):
        return None

    norm_map = {_normalize_index_label(i): i for i in df.index}
    for alias in aliases:
        hit = norm_map.get(_normalize_index_label(alias))
        if hit is None:
            continue
        return _to_float(df.loc[hit].iloc[col_pos], ndigits=ndigits)
    return None


def _quarterly_revenue_series(df: pd.DataFrame | None) -> list[tuple[str, float]]:
    if df is None or df.empty:
        return []

    norm_map = {_normalize_index_label(i): i for i in df.index}
    row_name = None
    for alias in ["Total Revenue", "Revenue", "Operating Revenue"]:
        row_name = norm_map.get(_normalize_index_label(alias))
        if row_name is not None:
            break
    if row_name is None:
        return []

    row = df.loc[row_name]
    values: list[tuple[str, float]] = []
    for col, v in row.items():
        fv = _to_float(v, ndigits=2)
        if fv is None:
            continue
        values.append((str(col)[:10], fv))
    values.sort(key=lambda x: x[0])
    return values


def _compute_growth_from_revenue(
    series: list[tuple[str, float]],
) -> dict[str, Any]:
    revenue_qoq_pct = None
    revenue_yoy_pct = None
    revenue_latest = None

    if len(series) >= 1:
        revenue_latest = series[-1][1]

    if len(series) >= 2:
        q_now = series[-1][1]
        q_prev = series[-2][1]
        qoq = _safe_div(q_now - q_prev, q_prev)
        if qoq is not None:
            revenue_qoq_pct = _to_float(qoq * 100, ndigits=2)

    if len(series) >= 5:
        q_now = series[-1][1]
        q_prev_year = series[-5][1]
        yoy = _safe_div(q_now - q_prev_year, q_prev_year)
        if yoy is not None:
            revenue_yoy_pct = _to_float(yoy * 100, ndigits=2)

    return {
        "revenue_latest": revenue_latest,
        "revenue_qoq_pct": revenue_qoq_pct,
        "revenue_yoy_pct": revenue_yoy_pct,
        "quarterly_revenue_series": [
            {"quarter": quarter, "revenue": value} for quarter, value in series[-8:]
        ],
    }


def _fetch_json_list(url: str, timeout: int = 15) -> list[dict[str, Any]]:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _match_code_from_rows(
    rows: list[dict[str, Any]], ticker: str
) -> dict[str, Any] | None:
    targets = {ticker.strip().upper()}
    if "." in ticker:
        targets.add(ticker.split(".")[0].strip().upper())

    code_keys = [
        "Code",
        "code",
        "證券代號",
        "SecuritiesCompanyCode",
        "股票代號",
        "公司代號",
    ]

    for row in rows:
        for k in code_keys:
            if k not in row:
                continue
            v = str(row.get(k, "")).strip().upper()
            if v in targets:
                return row
    return None


def _tw_valuation_from_row(row: dict[str, Any]) -> dict[str, float | None]:
    pe_keys = ["PEratio", "P/E", "本益比", "本益比", "本益比(倍)"]
    pb_keys = ["PBratio", "P/B", "股價淨值比", "股價淨值比(倍)"]
    dy_keys = ["DividendYield", "殖利率", "殖利率(%)", "現金殖利率", "殖利率％"]

    def pick(keys: list[str]) -> float | None:
        for key in keys:
            if key in row:
                return _to_float(row.get(key), ndigits=4)
        return None

    return {
        "pe_ratio": pick(pe_keys),
        "pb_ratio": pick(pb_keys),
        "dividend_yield_pct": pick(dy_keys),
    }


def _fetch_tw_official_valuation(
    ticker: str,
    board_hint: str,
) -> tuple[dict[str, float | None], dict[str, str], list[str], dict[str, Any]]:
    warnings: list[str] = []
    source_status: dict[str, str] = {}
    details: dict[str, Any] = {
        "provider": None,
        "endpoint": None,
        "raw_row": None,
    }

    base_ticker = ticker.split(".")[0].strip().upper()
    empty = {
        "pe_ratio": None,
        "pb_ratio": None,
        "dividend_yield_pct": None,
    }

    try_twse = board_hint in {"listed", "unknown"}
    try_tpex = board_hint in {"otc", "unknown"}

    if try_twse:
        try:
            rows = _fetch_json_list(_TWSE_BWIBBU_ALL)
            hit = _match_code_from_rows(rows, base_ticker)
            if hit:
                source_status["twse"] = "ok"
                details["provider"] = "twse"
                details["endpoint"] = _TWSE_BWIBBU_ALL
                details["raw_row"] = hit
                return _tw_valuation_from_row(hit), source_status, warnings, details
            source_status["twse"] = "not_found"
        except Exception as exc:
            source_status["twse"] = f"error: {exc}"
            warnings.append("TWSE 估值快照取得失敗")

    if try_tpex:
        tpex_found = False
        for url in _TPEX_PE_PB_YIELD_CANDIDATES:
            try:
                rows = _fetch_json_list(url)
                hit = _match_code_from_rows(rows, base_ticker)
                if hit:
                    source_status["tpex"] = f"ok ({url})"
                    tpex_found = True
                    details["provider"] = "tpex"
                    details["endpoint"] = url
                    details["raw_row"] = hit
                    return _tw_valuation_from_row(hit), source_status, warnings, details
            except Exception as exc:
                source_status["tpex"] = f"error: {exc}"
                warnings.append("TPEX 估值快照取得失敗")
                break
        if not tpex_found and "tpex" not in source_status:
            source_status["tpex"] = "not_found"

    return empty, source_status, warnings, details


def _build_yfinance_metrics(symbol: str) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    tk = yf.Ticker(symbol)

    info = tk.info or {}
    quarterly_financials = tk.quarterly_financials
    financials = tk.financials
    quarterly_balance_sheet = tk.quarterly_balance_sheet
    balance_sheet = tk.balance_sheet
    quarterly_cashflow = tk.quarterly_cashflow
    cashflow = tk.cashflow

    trailing_pe = _to_float(info.get("trailingPE"), ndigits=4)
    price_to_book = _to_float(info.get("priceToBook"), ndigits=4)
    dividend_yield = _normalize_dividend_yield_pct(info)

    roe = _to_float(info.get("returnOnEquity"), ndigits=6)
    if roe is not None:
        roe = _to_float(roe * 100, ndigits=2)

    net_margin = _to_float(info.get("profitMargins"), ndigits=6)
    if net_margin is not None:
        net_margin = _to_float(net_margin * 100, ndigits=2)

    eps = _to_float(info.get("trailingEps"), ndigits=4)
    if eps is None:
        eps = _to_float(info.get("epsTrailingTwelveMonths"), ndigits=4)

    if net_margin is None:
        net_income_annual = _row_value(
            financials, ["Net Income", "NetIncome"], col_pos=0
        )
        revenue_annual = _row_value(
            financials,
            ["Total Revenue", "Revenue", "Operating Revenue"],
            col_pos=0,
        )
        margin = _safe_div(net_income_annual, revenue_annual)
        if margin is not None:
            net_margin = _to_float(margin * 100, ndigits=2)

    if roe is None:
        net_income_q = _row_value(
            quarterly_financials,
            ["Net Income", "NetIncome"],
            col_pos=0,
        )
        equity_q = _row_value(
            quarterly_balance_sheet,
            [
                "Stockholders Equity",
                "Total Equity Gross Minority Interest",
                "Total Equity",
            ],
            col_pos=0,
        )
        roe_calc = _safe_div(net_income_q, equity_q)
        if roe_calc is not None:
            roe = _to_float(roe_calc * 400, ndigits=2)

    debt_to_equity = _to_float(info.get("debtToEquity"), ndigits=4)
    current_ratio = _to_float(info.get("currentRatio"), ndigits=4)

    if debt_to_equity is None:
        total_debt = _row_value(
            balance_sheet,
            [
                "Total Debt",
                "Long Term Debt And Capital Lease Obligation",
                "Long Term Debt",
            ],
            col_pos=0,
        )
        total_equity = _row_value(
            balance_sheet,
            [
                "Stockholders Equity",
                "Total Equity Gross Minority Interest",
                "Total Equity",
            ],
            col_pos=0,
        )
        d2e = _safe_div(total_debt, total_equity)
        if d2e is not None:
            debt_to_equity = _to_float(d2e, ndigits=4)

    free_cashflow = _to_float(info.get("freeCashflow"), ndigits=2)
    operating_cashflow = _to_float(info.get("operatingCashflow"), ndigits=2)

    if free_cashflow is None:
        ocf = _row_value(
            cashflow,
            ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
            col_pos=0,
            ndigits=2,
        )
        capex = _row_value(
            cashflow,
            ["Capital Expenditure", "CapitalExpenditure"],
            col_pos=0,
            ndigits=2,
        )
        if ocf is not None and capex is not None:
            free_cashflow = _to_float(ocf + capex, ndigits=2)

    revenue_series = _quarterly_revenue_series(quarterly_financials)
    growth = _compute_growth_from_revenue(revenue_series)

    if not revenue_series:
        warnings.append("季度營收序列不足，無法完整計算 YoY/QoQ")

    payload = {
        "valuation_snapshot": {
            "pe_ratio": trailing_pe,
            "pb_ratio": price_to_book,
            "dividend_yield_pct": dividend_yield,
            "source": "yfinance",
        },
        "profitability_data": {
            "roe_pct": roe,
            "eps": eps,
            "net_margin_pct": net_margin,
            "source": "yfinance",
        },
        "growth_data": {
            **growth,
            "monthly_revenue_yoy_pct": None,
            "monthly_revenue_trend": None,
            "source": "yfinance",
        },
        "financial_health_data": {
            "debt_to_equity": debt_to_equity,
            "current_ratio": current_ratio,
            "free_cashflow": free_cashflow,
            "operating_cashflow": operating_cashflow,
            "source": "yfinance",
        },
    }
    return payload, warnings


def _first_valid_symbol(candidates: list[str]) -> tuple[str, dict[str, Any]]:
    errors: list[str] = []
    for symbol in candidates:
        try:
            tk = yf.Ticker(symbol)
            info = tk.info or {}
            if info:
                return symbol, info
            errors.append(f"{symbol}: empty info")
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    raise RuntimeError(f"unable to resolve ticker via yfinance; errors={errors}")


def _build_signal_summary(
    valuation_snapshot: dict[str, Any],
    profitability_data: dict[str, Any],
    growth_data: dict[str, Any],
    financial_health_data: dict[str, Any],
) -> dict[str, str]:
    pe = valuation_snapshot.get("pe_ratio")
    dy = valuation_snapshot.get("dividend_yield_pct")
    roe = profitability_data.get("roe_pct")
    net_margin = profitability_data.get("net_margin_pct")
    yoy = growth_data.get("revenue_yoy_pct")
    qoq = growth_data.get("revenue_qoq_pct")
    d2e = financial_health_data.get("debt_to_equity")
    fcf = financial_health_data.get("free_cashflow")

    if pe is None:
        valuation_signal = "估值資料不足，無法判斷高估或低估"
    elif pe >= 30:
        valuation_signal = "本益比偏高，市場對成長預期較高"
    elif pe <= 12:
        valuation_signal = "本益比偏低，需確認是否反映基本面風險"
    else:
        valuation_signal = "本益比位於中性區間"

    if dy is not None and dy >= 5:
        valuation_signal = f"{valuation_signal}；現金殖利率約 {dy}%"

    if roe is None and net_margin is None:
        profitability_signal = "獲利能力資料不足"
    elif (roe is not None and roe >= 15) or (
        net_margin is not None and net_margin >= 15
    ):
        profitability_signal = "獲利能力偏強（ROE/淨利率至少一項表現良好）"
    else:
        profitability_signal = "獲利能力中性或偏弱，需持續追蹤"

    if yoy is None and qoq is None:
        growth_signal = "成長性資料不足"
    elif (yoy is not None and yoy > 0) and (qoq is None or qoq > 0):
        growth_signal = "營收動能偏正，年增率維持成長"
    elif yoy is not None and yoy < 0:
        growth_signal = "營收年增率為負，需關注需求是否轉弱"
    else:
        growth_signal = "營收動能方向不一致，短期趨勢待確認"

    if d2e is None and fcf is None:
        health_signal = "財務健康資料不足"
    elif (d2e is not None and d2e > 2.0) or (fcf is not None and fcf < 0):
        health_signal = "財務結構有壓力（高槓桿或自由現金流轉負）"
    else:
        health_signal = "財務結構大致穩健"

    return {
        "valuation": valuation_signal,
        "profitability": profitability_signal,
        "growth": growth_signal,
        "financial_health": health_signal,
    }


def get_fundamentals(ticker: str, date: str | None = None, market: str = "tw") -> str:
    try:
        m = _normalize_market(market)
        analysis_date = _parse_date(date) if date else _default_analysis_date()
        ticker_canonical = _canonical_ticker(m, ticker)
        paths = _cache_paths(
            market=m, ticker_canonical=ticker_canonical, analysis_date=analysis_date
        )
        cached_bundle = _read_json(paths["bundle"])
        manifest = _read_json(paths["manifest"]) or _new_manifest()

        warnings: list[str] = []
        if isinstance(cached_bundle, dict):
            warnings.extend(
                (((cached_bundle.get("data_quality") or {}).get("warnings")) or [])
            )

        valuation_fresh = _dataset_is_fresh(
            manifest, "valuation_snapshot", analysis_date
        )
        quarterly_fresh = _dataset_is_fresh(
            manifest, "quarterly_financials", analysis_date
        )
        monthly_fresh = _dataset_is_fresh(manifest, "monthly_revenue", analysis_date)

        valuation_snapshot: dict[str, Any] = (
            (cached_bundle or {}).get("valuation_snapshot", {})
            if valuation_fresh
            else {}
        )
        profitability_data: dict[str, Any] = (
            (cached_bundle or {}).get("profitability_data", {})
            if quarterly_fresh
            else {}
        )
        growth_data: dict[str, Any] = (
            (cached_bundle or {}).get("growth_data", {}) if quarterly_fresh else {}
        )
        financial_health_data: dict[str, Any] = (
            (cached_bundle or {}).get("financial_health_data", {})
            if quarterly_fresh
            else {}
        )

        monthly_series = ((growth_data or {}).get("monthly_revenue_series")) or []
        if not monthly_fresh and monthly_series:
            monthly_series = []

        if m == "us":
            resolved_symbol = ticker.strip().upper()
            resolved_board = "us"
        else:
            cached_symbol = ((cached_bundle or {}).get("instrument") or {}).get(
                "resolved_symbol"
            )
            if isinstance(cached_symbol, str) and cached_symbol:
                resolved_symbol = cached_symbol
            else:
                candidates = _tw_symbol_candidates(ticker)
                resolved_symbol, _ = _first_valid_symbol(candidates)
            resolved_board = _extract_board_from_symbol(resolved_symbol)

        need_yf_metrics = not (valuation_fresh and quarterly_fresh)
        yf_data: dict[str, Any] = {}
        if need_yf_metrics:
            yf_data, yf_warnings = _build_yfinance_metrics(resolved_symbol)
            warnings.extend(yf_warnings)
            info_for_snapshot = yf.Ticker(resolved_symbol).info or {}
            raw_file = _save_source_snapshot(
                sources_dir=paths["sources"],
                dataset="info",
                provider="yfinance",
                period=analysis_date.isoformat(),
                payload=info_for_snapshot,
            )
            source_nodes = (cached_bundle or {}).get("lineage", {}).get("sources", [])
            if not isinstance(source_nodes, list):
                source_nodes = []
            source_nodes.append(
                {
                    "dataset": "quarterly_financials",
                    "provider": "yfinance",
                    "endpoint": "Ticker.info + financial statements",
                    "fetched_at": _now_iso(),
                    "raw_file": raw_file,
                }
            )
            if not quarterly_fresh:
                profitability_data = yf_data["profitability_data"]
                growth_data = yf_data["growth_data"]
                growth_data["monthly_revenue_series"] = monthly_series
                financial_health_data = yf_data["financial_health_data"]
                _upsert_manifest_dataset(
                    manifest,
                    dataset="quarterly_financials",
                    period_end=analysis_date.isoformat(),
                    status="ok",
                )
                manifest.setdefault("last_fetch_status", {})["yfinance"] = "ok"
            if not valuation_fresh and m == "us":
                valuation_snapshot = yf_data["valuation_snapshot"]
                valuation_snapshot["source_confidence"] = "fallback"
                _upsert_manifest_dataset(
                    manifest,
                    dataset="valuation_snapshot",
                    period_end=analysis_date.isoformat(),
                    status="ok",
                )
                manifest.setdefault("last_fetch_status", {})["valuation"] = "yfinance"
        else:
            source_nodes = (cached_bundle or {}).get("lineage", {}).get("sources", [])
            if not isinstance(source_nodes, list):
                source_nodes = []

        official_status: dict[str, str] = {}
        fallback_chain: list[str] = []
        if m == "tw" and not valuation_fresh:
            board_hint = _resolve_tw_board_from_ticker(ticker)
            (
                official_valuation,
                official_status,
                official_warnings,
                official_details,
            ) = _fetch_tw_official_valuation(ticker=ticker, board_hint=board_hint)
            warnings.extend(official_warnings)

            if official_details.get("raw_row") is not None:
                raw_file = _save_source_snapshot(
                    sources_dir=paths["sources"],
                    dataset="valuation",
                    provider=str(official_details.get("provider") or "official"),
                    period=analysis_date.isoformat(),
                    payload=official_details["raw_row"],
                )
                source_nodes.append(
                    {
                        "dataset": "valuation",
                        "provider": str(official_details.get("provider") or "official"),
                        "endpoint": str(official_details.get("endpoint") or ""),
                        "fetched_at": _now_iso(),
                        "raw_file": raw_file,
                    }
                )

            valuation_snapshot = {
                "pe_ratio": official_valuation.get("pe_ratio"),
                "pb_ratio": official_valuation.get("pb_ratio"),
                "dividend_yield_pct": official_valuation.get("dividend_yield_pct"),
                "source": "TWSE/TPEX",
                "source_confidence": "official",
            }

            if (
                valuation_snapshot.get("pe_ratio") is None
                or valuation_snapshot.get("pb_ratio") is None
            ):
                fallback_chain.extend(["twse", "tpex", "yfinance"])
                if not yf_data:
                    yf_data, yf_warnings = _build_yfinance_metrics(resolved_symbol)
                    warnings.extend(yf_warnings)
                valuation_snapshot["pe_ratio"] = valuation_snapshot.get(
                    "pe_ratio"
                ) or yf_data["valuation_snapshot"].get("pe_ratio")
                valuation_snapshot["pb_ratio"] = valuation_snapshot.get(
                    "pb_ratio"
                ) or yf_data["valuation_snapshot"].get("pb_ratio")
                valuation_snapshot["dividend_yield_pct"] = valuation_snapshot.get(
                    "dividend_yield_pct"
                ) or yf_data["valuation_snapshot"].get("dividend_yield_pct")
                valuation_snapshot["source"] = "TWSE/TPEX (fallback yfinance)"
                valuation_snapshot["source_confidence"] = "fallback"
                manifest.setdefault("last_fetch_status", {})["valuation"] = (
                    "official_fallback_yfinance"
                )
            else:
                fallback_chain.extend(["twse", "tpex"])
                manifest.setdefault("last_fetch_status", {})["valuation"] = "official"

            _upsert_manifest_dataset(
                manifest,
                dataset="valuation_snapshot",
                period_end=analysis_date.isoformat(),
                status="ok",
            )

        if not monthly_series:
            warnings.append("目前無 MOPS 月營收序列，TW 月營收成長僅能顯示為缺值")
        if m == "tw":
            warnings.append(
                "TW 月營收與 MOPS 季報指標尚未接入，現階段以 yfinance 財務資料替代"
            )

        growth_data = growth_data or {}
        growth_data.setdefault("monthly_revenue_series", monthly_series)
        growth_data.setdefault("monthly_revenue_yoy_pct", None)
        growth_data.setdefault("monthly_revenue_trend", None)
        growth_data.setdefault(
            "quarterly",
            {
                "period_type": "quarter",
                "period_end": manifest.get("coverage", {}).get(
                    "quarterly_latest", analysis_date.isoformat()
                ),
                "revenue_latest": growth_data.get("revenue_latest"),
                "revenue_qoq_pct": growth_data.get("revenue_qoq_pct"),
                "revenue_yoy_pct": growth_data.get("revenue_yoy_pct"),
            },
        )

        valuation_snapshot = valuation_snapshot or {
            "pe_ratio": None,
            "pb_ratio": None,
            "dividend_yield_pct": None,
            "source": "unknown",
            "source_confidence": "fallback",
        }
        profitability_data = profitability_data or {
            "roe_pct": None,
            "eps": None,
            "net_margin_pct": None,
            "source": "unknown",
        }
        financial_health_data = financial_health_data or {
            "debt_to_equity": None,
            "current_ratio": None,
            "free_cashflow": None,
            "operating_cashflow": None,
            "source": "unknown",
        }

        missing_fields = [
            k
            for k in [
                "valuation_snapshot.pe_ratio",
                "valuation_snapshot.pb_ratio",
                "profitability_data.roe_pct",
                "profitability_data.eps",
                "financial_health_data.debt_to_equity",
            ]
            if {
                "valuation_snapshot.pe_ratio": valuation_snapshot.get("pe_ratio"),
                "valuation_snapshot.pb_ratio": valuation_snapshot.get("pb_ratio"),
                "profitability_data.roe_pct": profitability_data.get("roe_pct"),
                "profitability_data.eps": profitability_data.get("eps"),
                "financial_health_data.debt_to_equity": financial_health_data.get(
                    "debt_to_equity"
                ),
            }[k]
            is None
        ]

        signal_summary = _build_signal_summary(
            valuation_snapshot,
            profitability_data,
            growth_data,
            financial_health_data,
        )

        manifest.setdefault("coverage", {})["valuation_period_end"] = (
            analysis_date.isoformat()
        )
        manifest.setdefault("coverage", {})["quarterly_latest"] = (
            analysis_date.isoformat()
        )
        if monthly_series:
            latest_month = monthly_series[-1].get("period")
            if latest_month:
                manifest.setdefault("coverage", {})["monthly_revenue_latest"] = (
                    latest_month
                )
                _upsert_manifest_dataset(
                    manifest,
                    dataset="monthly_revenue",
                    period_end=str(latest_month),
                    status="cached",
                )

        bundle = {
            "schema_version": "fundamentals.bundle.v1",
            "instrument": {
                "market": m,
                "ticker_input": ticker,
                "ticker_canonical": ticker_canonical,
                "resolved_symbol": resolved_symbol,
                "board": resolved_board,
            },
            "as_of": {
                "analysis_date": analysis_date.isoformat(),
                "generated_at": _now_iso(),
            },
            "valuation_snapshot": {
                "period_type": "day",
                "period_end": analysis_date.isoformat(),
                **valuation_snapshot,
            },
            "profitability_data": {
                "period_type": "quarter",
                "period_end": manifest.get("coverage", {}).get(
                    "quarterly_latest", "unknown"
                ),
                **profitability_data,
            },
            "growth_data": growth_data,
            "financial_health_data": {
                "period_type": "quarter",
                "period_end": manifest.get("coverage", {}).get(
                    "quarterly_latest", "unknown"
                ),
                **financial_health_data,
            },
            "signal_summary": signal_summary,
            "data_quality": {
                "warnings": sorted(set(warnings)),
                "missing_fields": missing_fields,
                "staleness_days": _snapshot_staleness_days(manifest, analysis_date),
            },
            "lineage": {
                "sources": source_nodes,
                "fallback_chain": fallback_chain,
            },
        }

        _write_json(paths["bundle"], bundle)
        _write_json(paths["manifest"], manifest)

        payload = {
            "ok": True,
            "ticker": ticker,
            "resolved_symbol": resolved_symbol,
            "market": m,
            "board": resolved_board,
            "analysis_date": analysis_date.isoformat(),
            "schema_version": "fundamentals.bundle.v1",
            "cache": {
                "bundle_file": str(paths["bundle"].relative_to(_PROJECT_ROOT)),
                "manifest_file": str(paths["manifest"].relative_to(_PROJECT_ROOT)),
                "valuation_fresh": valuation_fresh,
                "quarterly_fresh": quarterly_fresh,
                "monthly_fresh": monthly_fresh,
            },
            "sources": {
                "valuation": (
                    "yfinance" if m == "us" else "TWSE/TPEX + yfinance fallback"
                ),
                "profitability": "yfinance",
                "growth": "yfinance" if m == "us" else "yfinance (MOPS pending)",
                "financial_health": "yfinance",
                "official_status": official_status,
            },
            "valuation_snapshot": bundle["valuation_snapshot"],
            "profitability_data": bundle["profitability_data"],
            "growth_data": bundle["growth_data"],
            "financial_health_data": bundle["financial_health_data"],
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
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )


fundamental_analyst = Agent(
    model="gemini-2.5-flash",
    name="fundamental_analyst",
    description="基本面分析師：以官方資料 + yfinance 產生可核對的 fundamentals_report。",
    tools=[get_fundamentals],
    output_key="fundamentals_report",
    instruction="""你是 AlphaCouncil 的基本面分析師。

任務規則：
1) 先呼叫一次 `get_fundamentals(ticker, date, market)`；若未提供 `date` 或 `market`，預設為今日（Asia/Taipei）與 `tw`。
2) 僅能使用工具回傳的資料撰寫報告，禁止捏造數值。
3) 若 `ok=false`，直接回報資料錯誤與可能原因，不要硬做結論。
4) 若 `data_quality.warnings` 非空，必須在「風險提示」完整揭露。
5) 職責邊界：只做基本面（估值、獲利、成長、財務健康），不得混入技術面、新聞語氣、籌碼或情緒面。

輸出格式（固定）：
### 基本面分析師報告

**分析日期**：<analysis_date>
**標的**：<ticker / resolved_symbol>
**市場**：<market>

#### 摘要
- 3 條最重要發現（優先引用 signal_summary）

#### 估值摘要
- P/E、P/B、現金殖利率（若為 TW，需提示官方/備援來源）

#### 獲利與成長
- ROE、EPS、Net Margin
- Revenue YoY / QoQ
- 若月營收資料缺失，明確說明「目前無 MOPS 月營收序列」

#### 財務健康
- Debt/Equity、Current Ratio、FCF、Operating Cash Flow

#### 風險提示
- 條列資料限制、指標衝突與潛在下行風險

最後加註：本報告僅供研究，不構成投資建議。
""",
)
