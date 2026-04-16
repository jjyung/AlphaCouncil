import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import urllib3
import yfinance as yf
from google.adk.agents.llm_agent import Agent
from requests.exceptions import SSLError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CHIP_DATA_ROOT = _PROJECT_ROOT / "alpha_council" / "data" / "chip"

_TTL_DAYS = {
    "market_chip": 1,
    "stock_chip": 1,
}

_TWSE_T86 = "https://openapi.twse.com.tw/v1/exchangeReport/T86"
_TWSE_MARGIN = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
_TAIFEX_PCR = "https://openapi.taifex.com.tw/v1/PutCallRatio"
_TAIFEX_FOREIGN_FUTURES = (
    "https://openapi.taifex.com.tw/v1/"
    "MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
)
_TAIFEX_LARGE_TRADER_OPTIONS = (
    "https://openapi.taifex.com.tw/v1/OpenInterestOfLargeTradersOptions"
)

_TWSE_RWD_T86 = (
    "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999"
)
_TWSE_RWD_T86_BY_DATE = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date={date}"
_TWSE_RWD_TWTASU = "https://www.twse.com.tw/rwd/zh/afterTrading/TWTASU?response=json"


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


def _to_num(raw: Any) -> float | None:
    s = str(raw).strip().replace(",", "")
    if not s or s in {"-", "--", "N/A", "NA", "None", "nan"}:
        return None
    s = s.replace("％", "%")
    if s.endswith("%"):
        s = s[:-1]
    s = re.sub(r"[^0-9.+\-]", "", s)
    if s in {"", "+", "-", "."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_float(v: Any, ndigits: int = 4) -> float | None:
    n = _to_num(v)
    if n is None:
        return None
    return round(float(n), ndigits)


def _safe_div(a: float | None, b: float | None, ndigits: int = 4) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(float(a / b), ndigits)


def _normalize_pct(raw: Any) -> float | None:
    n = _to_num(raw)
    if n is None:
        return None
    if 0 <= n <= 1:
        return round(n * 100, 4)
    return round(n, 4)


def _cache_paths(
    market: str,
    ticker_canonical: str,
    analysis_date: dt.date,
) -> dict[str, Path]:
    y = analysis_date.strftime("%Y")
    m = analysis_date.strftime("%m")
    base = _CHIP_DATA_ROOT / market / ticker_canonical / y / m
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
        "schema_version": "chip.bundle.v1",
        "created_at": now,
        "updated_at": now,
        "datasets": {},
        "coverage": {},
        "last_fetch_status": {},
    }


def _dataset_is_fresh(
    manifest: dict[str, Any] | None,
    dataset: str,
    today: dt.date,
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
    manifest: dict[str, Any],
    today: dt.date,
) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    datasets = manifest.get("datasets", {}) if isinstance(manifest, dict) else {}
    for dataset in _TTL_DAYS:
        fetched = _parse_iso_to_date(
            (datasets.get(dataset, {}) or {}).get("fetched_at")
        )
        out[dataset] = None if fetched is None else (today - fetched).days
    return out


def _fetch_json_list(url: str, timeout: int = 15) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=timeout)
    except SSLError:
        resp = requests.get(url, timeout=timeout, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _fetch_json_dict(url: str, timeout: int = 15) -> dict[str, Any]:
    try:
        resp = requests.get(url, timeout=timeout)
    except SSLError:
        resp = requests.get(url, timeout=timeout, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data
    return {}


def _match_code_from_rows(
    rows: list[dict[str, Any]],
    ticker: str,
) -> dict[str, Any] | None:
    targets = {ticker.strip().upper()}
    if "." in ticker:
        targets.add(ticker.split(".")[0].strip().upper())

    code_keys = [
        "Code",
        "code",
        "證券代號",
        "股票代號",
        "公司代號",
        "SecuritiesCompanyCode",
    ]

    for row in rows:
        for key in code_keys:
            if key not in row:
                continue
            v = str(row.get(key, "")).strip().upper()
            if v in targets:
                return row
    return None


def _pick_value(
    row: dict[str, Any], aliases: list[str], ndigits: int = 4
) -> float | None:
    for key in aliases:
        if key in row:
            return _to_float(row.get(key), ndigits=ndigits)
    return None


def _twse_t86_row_from_payload(
    payload: dict[str, Any],
    ticker_code: str,
) -> dict[str, Any] | None:
    fields = payload.get("fields") or []
    rows = payload.get("data") or []
    if not isinstance(fields, list) or not isinstance(rows, list):
        return None
    for raw in rows:
        if not isinstance(raw, list) or not raw:
            continue
        code = str(raw[0]).strip().upper()
        if code == ticker_code:
            return {
                str(fields[i]).strip(): raw[i]
                for i in range(min(len(fields), len(raw)))
            }
    return None


def _extract_twse_institutional_nets(row: dict[str, Any]) -> dict[str, float | None]:
    foreign = _pick_value(
        row,
        [
            "外陸資買賣超股數(不含外資自營商)",
            "外資及陸資(不含外資自營商)買賣超股數",
            "外資及陸資買賣超股數",
        ],
        ndigits=0,
    )
    trust = _pick_value(row, ["投信買賣超股數"], ndigits=0)
    dealer = _pick_value(
        row,
        ["自營商買賣超股數", "自營商買賣超股數(自行買賣)", "自營商買賣超股數(避險)"],
        ndigits=0,
    )
    total = _pick_value(row, ["三大法人買賣超股數"], ndigits=0)
    if total is None:
        total = _to_float((foreign or 0) + (trust or 0) + (dealer or 0), ndigits=0)
    return {
        "foreign_net_shares": foreign,
        "investment_trust_net_shares": trust,
        "dealer_net_shares": dealer,
        "total_net_shares": total,
    }


def _sign(v: float | None) -> int:
    if v is None:
        return 0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _continuity_from_history(history: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not history:
        return {"direction": "unknown", "days": 0}

    first = _sign(_to_num(history[0].get(key)))
    if first == 0:
        return {"direction": "flat", "days": 0}

    days = 0
    for item in history:
        s = _sign(_to_num(item.get(key)))
        if s != first:
            break
        days += 1

    return {"direction": "buy" if first > 0 else "sell", "days": int(days)}


def _fetch_twse_institutional_continuity(
    ticker_code: str,
    analysis_date: dt.date,
    latest_nets: dict[str, float | None],
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    source_nodes: list[dict[str, Any]] = []

    history: list[dict[str, Any]] = [
        {
            "date": analysis_date.isoformat(),
            "foreign_net_shares": latest_nets.get("foreign_net_shares"),
            "investment_trust_net_shares": latest_nets.get(
                "investment_trust_net_shares"
            ),
            "dealer_net_shares": latest_nets.get("dealer_net_shares"),
            "total_net_shares": latest_nets.get("total_net_shares"),
        }
    ]

    found_days = 1
    max_calendar_days = 20
    target_days = 7

    for i in range(1, max_calendar_days + 1):
        if found_days >= target_days:
            break
        d = analysis_date - dt.timedelta(days=i)
        d_raw = d.strftime("%Y%m%d")
        url = _TWSE_RWD_T86_BY_DATE.format(date=d_raw)
        try:
            payload = _fetch_json_dict(url)
            row = _twse_t86_row_from_payload(payload, ticker_code)
            if not row:
                continue
            nets = _extract_twse_institutional_nets(row)
            history.append({"date": d.isoformat(), **nets})
            found_days += 1
        except Exception:
            continue

    if len(history) <= 1:
        warnings.append("連買連賣歷史不足，continuity_days 可信度有限")

    continuity = {
        "foreign": _continuity_from_history(history, "foreign_net_shares"),
        "investment_trust": _continuity_from_history(
            history, "investment_trust_net_shares"
        ),
        "dealer": _continuity_from_history(history, "dealer_net_shares"),
        "total": _continuity_from_history(history, "total_net_shares"),
        "observed_trading_days": len(history),
    }

    source_nodes.append(
        {
            "dataset": "institutional_continuity",
            "provider": "twse_rwd",
            "endpoint": _TWSE_RWD_T86_BY_DATE,
            "fetched_at": _now_iso(),
            "observed_trading_days": len(history),
        }
    )

    return continuity, warnings, source_nodes


def _taifex_latest_rows(
    rows: list[dict[str, Any]],
    analysis_date: dt.date,
) -> tuple[str | None, list[dict[str, Any]]]:
    target = analysis_date.isoformat().replace("-", "")
    latest = ""
    for row in rows:
        d = str(row.get("Date", "")).strip()
        if len(d) == 8 and d <= target and d > latest:
            latest = d
    if not latest:
        return None, []
    return latest, [r for r in rows if str(r.get("Date", "")).strip() == latest]


def _is_foreign_item(item: Any) -> bool:
    s = str(item or "").strip().lower()
    return ("外資" in s) or ("foreign" in s)


def _is_tx_futures_contract(contract: Any) -> bool:
    s = str(contract or "").strip().lower()
    return any(k in s for k in ["臺股期貨", "台股期貨", "tx", "taiwan index"])


def _fetch_taifex_foreign_futures_oi(
    analysis_date: dt.date,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "as_of": None,
        "provider": "taifex_openapi",
        "foreign_futures_oi_long": None,
        "foreign_futures_oi_short": None,
        "foreign_futures_oi_net": None,
    }
    try:
        rows = _fetch_json_list(_TAIFEX_FOREIGN_FUTURES)
        if not rows:
            warnings.append("TAIFEX 外資期貨未平倉回傳空資料")
            return payload, warnings

        date_raw, latest_rows = _taifex_latest_rows(rows, analysis_date)
        if not latest_rows or not date_raw:
            warnings.append("TAIFEX 外資期貨未平倉在 analysis_date 前無資料")
            return payload, warnings

        candidates = [
            r
            for r in latest_rows
            if _is_foreign_item(r.get("Item"))
            and _is_tx_futures_contract(r.get("ContractCode"))
        ]
        if not candidates:
            candidates = [r for r in latest_rows if _is_foreign_item(r.get("Item"))]
        if not candidates:
            warnings.append("TAIFEX 外資期貨未平倉找不到外資身份別")
            return payload, warnings

        row = candidates[0]
        long_oi = _to_float(row.get("OpenInterest(Long)"), ndigits=0)
        short_oi = _to_float(row.get("OpenInterest(Short)"), ndigits=0)
        net_oi = _to_float(row.get("OpenInterest(Net)"), ndigits=0)
        if net_oi is None:
            net_oi = _to_float((long_oi or 0) - (short_oi or 0), ndigits=0)

        payload["as_of"] = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        payload["foreign_futures_oi_long"] = long_oi
        payload["foreign_futures_oi_short"] = short_oi
        payload["foreign_futures_oi_net"] = net_oi
        if long_oi is None and short_oi is None and net_oi is None:
            warnings.append("TAIFEX 外資期貨未平倉欄位解析失敗")
    except Exception as exc:
        warnings.append(f"TAIFEX 外資期貨未平倉抓取失敗: {exc}")

    return payload, warnings


def _fetch_taifex_large_trader_pcr_top5(
    analysis_date: dt.date,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "as_of": None,
        "provider": "taifex_openapi",
        "large_trader_top5_put_oi": None,
        "large_trader_top5_call_oi": None,
        "large_trader_pcr_top5": None,
        "settlement_month": None,
    }
    try:
        rows = _fetch_json_list(_TAIFEX_LARGE_TRADER_OPTIONS)
        if not rows:
            warnings.append("TAIFEX 大額交易人選擇權 OI 回傳空資料")
            return payload, warnings

        date_raw, latest_rows = _taifex_latest_rows(rows, analysis_date)
        if not latest_rows or not date_raw:
            warnings.append("TAIFEX 大額交易人選擇權 OI 在 analysis_date 前無資料")
            return payload, warnings

        txo_rows = [
            r
            for r in latest_rows
            if str(r.get("Contract", "")).strip().upper() == "TXO"
            and str(r.get("TypeOfTraders", "")).strip() == "0"
        ]
        if not txo_rows:
            txo_rows = [
                r
                for r in latest_rows
                if str(r.get("Contract", "")).strip().upper() == "TXO"
            ]
        if not txo_rows:
            warnings.append("TAIFEX 大額交易人選擇權 OI 找不到 TXO 資料")
            return payload, warnings

        month_priority = ["999912", "666666"]
        month = None
        months = sorted({str(r.get("SettlementMonth", "")).strip() for r in txo_rows})
        for m in month_priority:
            if m in months:
                month = m
                break
        if month is None and months:
            month = months[0]

        rows_m = [
            r for r in txo_rows if str(r.get("SettlementMonth", "")).strip() == month
        ]
        if not rows_m:
            warnings.append("TAIFEX 大額交易人選擇權 OI 找不到可用到期月份")
            return payload, warnings

        call_row = next(
            (
                r
                for r in rows_m
                if ("買權" in str(r.get("CallPut", "")))
                or (str(r.get("CallPut", "")).strip().lower() == "call")
            ),
            None,
        )
        put_row = next(
            (
                r
                for r in rows_m
                if ("賣權" in str(r.get("CallPut", "")))
                or (str(r.get("CallPut", "")).strip().lower() == "put")
            ),
            None,
        )

        call_oi = _to_float((call_row or {}).get("Top5Buy"), ndigits=0)
        put_oi = _to_float((put_row or {}).get("Top5Buy"), ndigits=0)
        pcr = _safe_div(put_oi, call_oi, ndigits=4)

        payload["as_of"] = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        payload["settlement_month"] = month
        payload["large_trader_top5_put_oi"] = put_oi
        payload["large_trader_top5_call_oi"] = call_oi
        payload["large_trader_pcr_top5"] = pcr

        if put_oi is None or call_oi is None:
            warnings.append("TAIFEX 大額交易人 Top5 OI 解析不完整")
        elif pcr is None:
            warnings.append("TAIFEX 大額交易人 Top5 PCR 無法計算")
    except Exception as exc:
        warnings.append(f"TAIFEX 大額交易人選擇權 OI 抓取失敗: {exc}")

    return payload, warnings


def _fetch_taifex_pcr(analysis_date: dt.date) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "provider": "taifex_openapi",
        "as_of": None,
        "market_pcr_volume": None,
        "market_pcr_oi": None,
    }
    try:
        data = _fetch_json_list(_TAIFEX_PCR)
        if not data:
            warnings.append("TAIFEX PutCallRatio 回傳空資料")
            return payload, warnings

        target = analysis_date.isoformat().replace("-", "")
        best: dict[str, Any] | None = None
        for record in data:
            rec_date = str(record.get("Date", "")).strip()
            if len(rec_date) != 8:
                continue
            if rec_date > target:
                continue
            if best is None or rec_date > best["_raw_date"]:
                vol_raw = _to_num(record.get("PutCallVolumeRatio%"))
                oi_raw = _to_num(record.get("PutCallOIRatio%"))
                best = {
                    "_raw_date": rec_date,
                    "as_of": f"{rec_date[:4]}-{rec_date[4:6]}-{rec_date[6:8]}",
                    "market_pcr_volume": _to_float(vol_raw / 100, 4)
                    if vol_raw is not None
                    else None,
                    "market_pcr_oi": _to_float(oi_raw / 100, 4)
                    if oi_raw is not None
                    else None,
                }

        if best is None:
            warnings.append("TAIFEX PutCallRatio 在 analysis_date 前沒有可用資料")
            return payload, warnings

        payload["as_of"] = best["as_of"]
        payload["market_pcr_volume"] = best["market_pcr_volume"]
        payload["market_pcr_oi"] = best["market_pcr_oi"]
        if payload["market_pcr_volume"] is None:
            warnings.append("TAIFEX PCR(volume) 解析失敗")
        if payload["market_pcr_oi"] is None:
            warnings.append("TAIFEX PCR(OI) 解析失敗")
    except Exception as exc:
        warnings.append(f"TAIFEX PutCallRatio 抓取失敗: {exc}")

    return payload, warnings


def _fetch_tw_stock_chip(
    ticker: str,
    analysis_date: dt.date,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    source_nodes: list[dict[str, Any]] = []
    stock_payload: dict[str, Any] = {
        "provider": "twse_mixed",
        "as_of": analysis_date.isoformat(),
        "institutional_spot": {
            "foreign_net_shares": None,
            "investment_trust_net_shares": None,
            "dealer_net_shares": None,
            "total_net_shares": None,
            "continuity_days": {
                "foreign": {"direction": "unknown", "days": 0},
                "investment_trust": {"direction": "unknown", "days": 0},
                "dealer": {"direction": "unknown", "days": 0},
                "total": {"direction": "unknown", "days": 0},
                "observed_trading_days": 0,
            },
        },
        "leverage_and_short": {
            "margin_balance_shares": None,
            "short_balance_shares": None,
            "short_to_margin_ratio": None,
            "margin_short_sell_shares": None,
            "borrow_short_sell_shares": None,
        },
        "warrant_proxy": {
            "warrant_bullish_ratio": None,
            "warrant_activity_score": None,
            "note": "權證指標尚未接入，先保留欄位。",
        },
    }

    ticker_code = ticker.split(".")[0].strip().upper()

    try:
        t86 = _fetch_json_dict(_TWSE_RWD_T86)
        inst_hit = _twse_t86_row_from_payload(t86, ticker_code)
        if inst_hit:
            nets = _extract_twse_institutional_nets(inst_hit)
            continuity, continuity_warn, continuity_nodes = (
                _fetch_twse_institutional_continuity(
                    ticker_code=ticker_code,
                    analysis_date=analysis_date,
                    latest_nets=nets,
                )
            )
            warnings.extend(continuity_warn)

            stock_payload["institutional_spot"] = {
                **nets,
                "continuity_days": continuity
                if isinstance(continuity, dict)
                else stock_payload["institutional_spot"]["continuity_days"],
            }
            source_nodes.append(
                {
                    "dataset": "institutional_spot",
                    "provider": "twse_rwd",
                    "endpoint": _TWSE_RWD_T86,
                    "fetched_at": _now_iso(),
                }
            )
            source_nodes.extend(continuity_nodes)
        else:
            warnings.append("TWSE T86 找不到該標的，法人買賣超缺值")
    except Exception as exc:
        warnings.append(f"TWSE T86 抓取失敗: {exc}")

    try:
        margin_rows = _fetch_json_list(_TWSE_MARGIN)
        margin_hit = _match_code_from_rows(margin_rows, ticker_code)
        if margin_hit:
            margin_balance = _pick_value(
                margin_hit,
                [
                    "MarginPurchaseTodayBalance",
                    "今日融資餘額",
                    "融資餘額",
                    "融資今日餘額",
                ],
                ndigits=0,
            )
            short_balance = _pick_value(
                margin_hit,
                [
                    "ShortSaleTodayBalance",
                    "今日融券餘額",
                    "融券餘額",
                    "融券今日餘額",
                ],
                ndigits=0,
            )
            short_ratio = _safe_div(short_balance, margin_balance, ndigits=4)

            stock_payload["leverage_and_short"] = {
                "margin_balance_shares": margin_balance,
                "short_balance_shares": short_balance,
                "short_to_margin_ratio": short_ratio,
                "margin_short_sell_shares": _pick_value(
                    margin_hit,
                    ["融券賣出", "ShortSale", "ShortSaleSell"],
                    ndigits=0,
                ),
                "borrow_short_sell_shares": None,
            }
            source_nodes.append(
                {
                    "dataset": "leverage_and_short",
                    "provider": "twse_openapi",
                    "endpoint": _TWSE_MARGIN,
                    "fetched_at": _now_iso(),
                }
            )
        else:
            warnings.append("TWSE MI_MARGN 找不到該標的，融資融券缺值")
    except Exception as exc:
        warnings.append(f"TWSE MI_MARGN 抓取失敗: {exc}")

    try:
        twtasu = _fetch_json_dict(_TWSE_RWD_TWTASU)
        fields = twtasu.get("fields") or []
        rows = twtasu.get("data") or []
        borrow_qty = None
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, list) or not raw:
                    continue
                sec_name = str(raw[0]).strip()
                m = re.match(r"^([0-9A-Z]{3,8})", sec_name)
                if not m:
                    continue
                code = m.group(1).upper()
                if code != ticker_code:
                    continue
                if len(raw) >= 4:
                    borrow_qty = _to_float(raw[3], ndigits=0)
                break

        if borrow_qty is not None:
            stock_payload["leverage_and_short"]["borrow_short_sell_shares"] = borrow_qty
            source_nodes.append(
                {
                    "dataset": "borrow_short_sell",
                    "provider": "twse_rwd",
                    "endpoint": _TWSE_RWD_TWTASU,
                    "fetched_at": _now_iso(),
                    "fields": fields,
                }
            )
        else:
            warnings.append("TWSE TWTASU 找不到該標的借券賣出資料")
    except Exception as exc:
        warnings.append(f"TWSE TWTASU 抓取失敗: {exc}")

    continuity_days = stock_payload["institutional_spot"].get("continuity_days", {})
    if (
        not isinstance(continuity_days, dict)
        or int(continuity_days.get("observed_trading_days", 0)) <= 1
    ):
        warnings.append("個股連買連賣天數資料不足，continuity_days 可信度有限")
    if stock_payload["leverage_and_short"].get("borrow_short_sell_shares") is None:
        warnings.append("借券賣出資料缺失，borrow_short_sell_shares 先留空")

    return stock_payload, warnings, source_nodes


def _fetch_us_market_chip(
    analysis_date: dt.date,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "provider": "yfinance",
        "as_of": analysis_date.isoformat(),
        "benchmark": "SPY",
        "institutional_holding_pct": None,
        "short_percent_of_float_pct": None,
        "note": "US 大盤籌碼使用 ETF proxy，僅輔助判讀。",
    }
    try:
        info = yf.Ticker("SPY").info or {}
        payload["institutional_holding_pct"] = _normalize_pct(
            info.get("heldPercentInstitutions")
        )
        payload["short_percent_of_float_pct"] = _normalize_pct(
            info.get("shortPercentOfFloat")
        )
        if payload["institutional_holding_pct"] is None:
            warnings.append("SPY heldPercentInstitutions 缺值")
        if payload["short_percent_of_float_pct"] is None:
            warnings.append("SPY shortPercentOfFloat 缺值")
    except Exception as exc:
        warnings.append(f"US market proxy 抓取失敗: {exc}")
    return payload, warnings


def _fetch_us_stock_chip(
    ticker: str,
    analysis_date: dt.date,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    source_nodes: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "provider": "yfinance",
        "as_of": analysis_date.isoformat(),
        "institutional_holders": {
            "held_percent_institutions": None,
            "held_percent_insiders": None,
            "institutional_holders_count": None,
        },
        "short_interest": {
            "short_percent_of_float_pct": None,
            "short_percent_of_shares_outstanding_pct": None,
            "shares_short": None,
        },
        "warrant_proxy": {
            "warrant_bullish_ratio": None,
            "warrant_activity_score": None,
            "note": "US 市場不使用權證欄位，保留空值。",
        },
    }

    symbol = ticker.strip().upper()
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}

        payload["institutional_holders"] = {
            "held_percent_institutions": _normalize_pct(
                info.get("heldPercentInstitutions")
            ),
            "held_percent_insiders": _normalize_pct(info.get("heldPercentInsiders")),
            "institutional_holders_count": None,
        }

        holders_df = tk.institutional_holders
        if isinstance(holders_df, pd.DataFrame) and not holders_df.empty:
            payload["institutional_holders"]["institutional_holders_count"] = int(
                len(holders_df)
            )

        payload["short_interest"] = {
            "short_percent_of_float_pct": _normalize_pct(
                info.get("shortPercentOfFloat")
            ),
            "short_percent_of_shares_outstanding_pct": _normalize_pct(
                info.get("sharesPercentSharesOut")
            ),
            "shares_short": _to_float(info.get("sharesShort"), ndigits=0),
        }

        if payload["institutional_holders"]["held_percent_institutions"] is None:
            warnings.append("US heldPercentInstitutions 缺值")
        if payload["short_interest"]["short_percent_of_float_pct"] is None:
            warnings.append("US shortPercentOfFloat 缺值")

        source_nodes.append(
            {
                "dataset": "stock_chip_info",
                "provider": "yfinance",
                "endpoint": "Ticker.info + institutional_holders",
                "fetched_at": _now_iso(),
            }
        )
    except Exception as exc:
        warnings.append(f"US stock chip 抓取失敗: {exc}")

    return payload, warnings, source_nodes


def _derive_signals(
    market: str,
    market_chip: dict[str, Any],
    stock_chip: dict[str, Any],
) -> dict[str, Any]:
    risk_flags: list[str] = []

    if market == "tw":
        pcr_vol = _to_num(market_chip.get("market_pcr_volume"))
        pcr_oi = _to_num(market_chip.get("market_pcr_oi"))
        foreign_net = _to_num(market_chip.get("foreign_futures_oi_net"))
        large_pcr = _to_num(market_chip.get("large_trader_pcr_top5"))

        if pcr_vol is None and pcr_oi is None:
            market_state = "大盤籌碼資料不足"
        elif (pcr_vol is not None and pcr_vol > 1.15) and (
            pcr_oi is not None and pcr_oi > 1.15
        ):
            market_state = "大盤衍生品偏避險（偏空）"
            risk_flags.append("PCR 雙口徑偏高，需留意避險情緒升溫")
        elif (pcr_vol is not None and pcr_vol < 0.85) and (
            pcr_oi is not None and pcr_oi < 0.85
        ):
            market_state = "大盤衍生品偏投機（偏多）"
            risk_flags.append("PCR 雙口徑偏低，需留意短線過熱")
        else:
            market_state = "大盤衍生品中性"

        if foreign_net is not None:
            if foreign_net > 0:
                market_state = f"{market_state}；外資期貨未平倉淨額偏多"
            elif foreign_net < 0:
                market_state = f"{market_state}；外資期貨未平倉淨額偏空"
                risk_flags.append("外資期貨未平倉淨額為負，留意大盤壓力")

        if large_pcr is not None:
            if large_pcr >= 1.2:
                market_state = f"{market_state}；大額交易人偏避險"
                risk_flags.append("大額交易人 Top5 PCR 偏高，避險需求升溫")
            elif large_pcr <= 0.8:
                market_state = f"{market_state}；大額交易人偏多"
                risk_flags.append("大額交易人 Top5 PCR 偏低，留意短線過熱")

        inst = stock_chip.get("institutional_spot", {})
        foreign = _to_num(inst.get("foreign_net_shares"))
        trust = _to_num(inst.get("investment_trust_net_shares"))
        dealer = _to_num(inst.get("dealer_net_shares"))
        total = _to_num(inst.get("total_net_shares"))
        if total is None and any(v is not None for v in [foreign, trust, dealer]):
            total = (foreign or 0) + (trust or 0) + (dealer or 0)

        if total is None:
            stock_state = "個股法人現貨資料不足"
        elif total > 0:
            stock_state = "個股法人現貨偏買方"
        elif total < 0:
            stock_state = "個股法人現貨偏賣方"
            risk_flags.append("三大法人現貨為賣超，短線承壓")
        else:
            stock_state = "個股法人現貨中性"

        continuity = inst.get("continuity_days", {})
        total_cont = continuity.get("total", {}) if isinstance(continuity, dict) else {}
        cont_days = int(total_cont.get("days", 0) or 0)
        cont_dir = str(total_cont.get("direction", "")).strip().lower()
        if cont_days >= 3 and cont_dir == "buy":
            stock_state = f"{stock_state}；三大法人連買 {cont_days} 日"
        elif cont_days >= 3 and cont_dir == "sell":
            stock_state = f"{stock_state}；三大法人連賣 {cont_days} 日"
            risk_flags.append("三大法人連續賣超，需留意籌碼轉弱")

        leverage = stock_chip.get("leverage_and_short", {})
        short_ratio = _to_num(leverage.get("short_to_margin_ratio"))
        borrow_short = _to_num(leverage.get("borrow_short_sell_shares"))
        if short_ratio is None:
            leverage_state = "槓桿與放空資料不足"
        elif short_ratio >= 0.4:
            leverage_state = "融券相對融資比重偏高，放空壓力偏大"
            risk_flags.append("short_to_margin_ratio 偏高，留意空方壓力")
        elif short_ratio <= 0.15:
            leverage_state = "融券比重偏低，放空壓力有限"
        else:
            leverage_state = "融資融券比重中性"

        if borrow_short is not None and borrow_short > 0:
            leverage_state = f"{leverage_state}；借券賣出量 {int(borrow_short)}"
            if borrow_short >= 1000:
                risk_flags.append("借券賣出量偏高，留意中短期空方壓力")

    else:
        m_inst = _to_num(market_chip.get("institutional_holding_pct"))
        m_short = _to_num(market_chip.get("short_percent_of_float_pct"))
        if m_inst is None and m_short is None:
            market_state = "US 大盤籌碼 proxy 資料不足"
        elif m_short is not None and m_short >= 4:
            market_state = "US 大盤 proxy 顯示避險偏高"
        else:
            market_state = "US 大盤 proxy 中性"

        holders = stock_chip.get("institutional_holders", {})
        short_interest = stock_chip.get("short_interest", {})
        held_inst = _to_num(holders.get("held_percent_institutions"))
        short_pct = _to_num(short_interest.get("short_percent_of_float_pct"))

        if held_inst is None and short_pct is None:
            stock_state = "US 個股籌碼資料不足"
        elif short_pct is not None and short_pct >= 10:
            stock_state = "US 個股空方壓力偏高"
            risk_flags.append("shortPercentOfFloat 偏高，留意軋空/下行雙向波動")
        elif (
            held_inst is not None
            and held_inst >= 60
            and (short_pct is None or short_pct <= 5)
        ):
            stock_state = "US 個股機構持有占比高，籌碼相對穩定"
        else:
            stock_state = "US 個股籌碼中性或訊號分歧"

        if short_pct is None:
            leverage_state = "US short interest 缺值"
        elif short_pct >= 10:
            leverage_state = "short interest 偏高"
        elif short_pct <= 3:
            leverage_state = "short interest 偏低"
        else:
            leverage_state = "short interest 中性"

    confidence_notes: list[str] = []
    if "資料不足" in market_state or "缺值" in market_state:
        confidence_notes.append("大盤籌碼證據不足，判讀信心下降")
    if "資料不足" in stock_state or "缺值" in stock_state:
        confidence_notes.append("個股籌碼證據不足，判讀信心下降")
    if "資料不足" in leverage_state or "缺值" in leverage_state:
        confidence_notes.append("槓桿/放空資料不足，風險判讀偏保守")

    return {
        "market_chip_state": market_state,
        "stock_chip_state": stock_state,
        "leverage_pressure": leverage_state,
        "risk_flags": risk_flags,
        "confidence_notes": confidence_notes,
    }


def get_chip_data(
    ticker: str,
    date: str | None = None,
    market: str = "tw",
    force_refresh: bool = False,
) -> str:
    try:
        m = _normalize_market(market)
        analysis_date = _default_analysis_date() if not date else _parse_date(date)
        ticker_canonical = _canonical_ticker(m, ticker)

        paths = _cache_paths(m, ticker_canonical, analysis_date)
        cached_bundle = _read_json(paths["bundle"]) or {}
        manifest = _read_json(paths["manifest"]) or _new_manifest()

        required = ["market_chip", "stock_chip"]
        fresh_map = {
            ds: _dataset_is_fresh(manifest, ds, analysis_date) for ds in required
        }
        all_fresh = all(fresh_map.values()) if fresh_map else False

        if (
            not force_refresh
            and isinstance(cached_bundle, dict)
            and cached_bundle.get("schema_version") == "chip.bundle.v1"
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
                "schema_version": "chip.bundle.v1",
                "cache": {
                    "bundle_file": str(paths["bundle"].relative_to(_PROJECT_ROOT)),
                    "manifest_file": str(paths["manifest"].relative_to(_PROJECT_ROOT)),
                    "cache_hit": True,
                    "force_refresh": False,
                    "fresh_map": fresh_map,
                },
                "chip_snapshot": cached_bundle.get("chip_snapshot", {}),
                "signal_summary": cached_bundle.get("signal_summary", {}),
                "data_quality": cached_bundle.get("data_quality", {}),
                "lineage": cached_bundle.get("lineage", {}),
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        snapshot: dict[str, Any] = {
            "market_chip": (cached_bundle.get("chip_snapshot") or {}).get(
                "market_chip", {}
            ),
            "stock_chip": (cached_bundle.get("chip_snapshot") or {}).get(
                "stock_chip", {}
            ),
        }

        source_map: dict[str, dict[str, Any]] = {}
        for node in (cached_bundle.get("lineage") or {}).get("sources", []):
            if isinstance(node, dict) and node.get("dataset"):
                source_map[str(node["dataset"])] = node

        warnings: list[str] = []

        def should_fetch(dataset: str) -> bool:
            if force_refresh:
                return True
            return not fresh_map.get(dataset, False)

        if should_fetch("market_chip"):
            if m == "tw":
                market_chip, market_warn = _fetch_taifex_pcr(analysis_date)
                foreign_payload, foreign_warn = _fetch_taifex_foreign_futures_oi(
                    analysis_date
                )
                large_payload, large_warn = _fetch_taifex_large_trader_pcr_top5(
                    analysis_date
                )
                market_chip["foreign_futures_oi_long"] = foreign_payload.get(
                    "foreign_futures_oi_long"
                )
                market_chip["foreign_futures_oi_short"] = foreign_payload.get(
                    "foreign_futures_oi_short"
                )
                market_chip["foreign_futures_oi_net"] = foreign_payload.get(
                    "foreign_futures_oi_net"
                )
                market_chip["large_trader_top5_put_oi"] = large_payload.get(
                    "large_trader_top5_put_oi"
                )
                market_chip["large_trader_top5_call_oi"] = large_payload.get(
                    "large_trader_top5_call_oi"
                )
                market_chip["large_trader_pcr_top5"] = large_payload.get(
                    "large_trader_pcr_top5"
                )
                market_chip["large_trader_settlement_month"] = large_payload.get(
                    "settlement_month"
                )
                warnings.extend(market_warn)
                warnings.extend(foreign_warn)
                warnings.extend(large_warn)
            else:
                market_chip, market_warn = _fetch_us_market_chip(analysis_date)
                warnings.extend(market_warn)

            market_status = "ok"
            if m == "tw":
                v = market_chip.get("market_pcr_volume")
                oi = market_chip.get("market_pcr_oi")
                if v is None and oi is None:
                    market_status = "error"
                elif v is None or oi is None:
                    market_status = "partial"
            else:
                inst = market_chip.get("institutional_holding_pct")
                short = market_chip.get("short_percent_of_float_pct")
                if inst is None and short is None:
                    market_status = "partial"
                elif inst is None or short is None:
                    market_status = "partial"

            snapshot["market_chip"] = market_chip
            period_end = market_chip.get("as_of") or analysis_date.isoformat()
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="market_chip",
                provider=str(market_chip.get("provider", "mixed")),
                period=period_end,
                payload=market_chip,
            )
            source_map["market_chip"] = {
                "dataset": "market_chip",
                "provider": str(market_chip.get("provider", "mixed")),
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            _upsert_manifest_dataset(manifest, "market_chip", period_end, market_status)
            manifest.setdefault("coverage", {})["market_chip_period_end"] = period_end
            manifest.setdefault("last_fetch_status", {})["market_chip"] = market_status

        if should_fetch("stock_chip"):
            if m == "tw":
                stock_chip, stock_warn, source_nodes = _fetch_tw_stock_chip(
                    ticker_canonical, analysis_date
                )
            else:
                stock_chip, stock_warn, source_nodes = _fetch_us_stock_chip(
                    ticker_canonical, analysis_date
                )

            warnings.extend(stock_warn)

            stock_status = "ok"
            if m == "tw":
                inst = stock_chip.get("institutional_spot", {})
                lev = stock_chip.get("leverage_and_short", {})
                has_inst = any(
                    inst.get(k) is not None
                    for k in [
                        "foreign_net_shares",
                        "investment_trust_net_shares",
                        "dealer_net_shares",
                        "total_net_shares",
                    ]
                )
                has_lev = any(
                    lev.get(k) is not None
                    for k in [
                        "margin_balance_shares",
                        "short_balance_shares",
                        "short_to_margin_ratio",
                        "margin_short_sell_shares",
                        "borrow_short_sell_shares",
                    ]
                )
                if not has_inst and not has_lev:
                    stock_status = "error"
                elif not has_inst or not has_lev:
                    stock_status = "partial"
            else:
                holders = stock_chip.get("institutional_holders", {})
                short_interest = stock_chip.get("short_interest", {})
                has_holder = holders.get("held_percent_institutions") is not None
                has_short = short_interest.get("short_percent_of_float_pct") is not None
                if not has_holder and not has_short:
                    stock_status = "error"
                elif not has_holder or not has_short:
                    stock_status = "partial"

            snapshot["stock_chip"] = stock_chip

            period_end = stock_chip.get("as_of") or analysis_date.isoformat()
            source_file = _save_source_snapshot(
                paths["sources"],
                dataset="stock_chip",
                provider=str(stock_chip.get("provider", "mixed")),
                period=period_end,
                payload=stock_chip,
            )
            source_map["stock_chip"] = {
                "dataset": "stock_chip",
                "provider": str(stock_chip.get("provider", "mixed")),
                "period_end": period_end,
                "fetched_at": _now_iso(),
                "file": source_file,
            }
            for i, node in enumerate(source_nodes, start=1):
                key = str(node.get("dataset", f"stock_chip_detail_{i}"))
                if key in source_map:
                    key = f"{key}_{i}"
                enriched = dict(node)
                enriched.setdefault("file", source_file)
                source_map[key] = enriched

            _upsert_manifest_dataset(manifest, "stock_chip", period_end, stock_status)
            manifest.setdefault("coverage", {})["stock_chip_period_end"] = period_end
            manifest.setdefault("last_fetch_status", {})["stock_chip"] = stock_status

        signals = _derive_signals(
            m, snapshot.get("market_chip", {}), snapshot.get("stock_chip", {})
        )

        market_node = snapshot.get("market_chip", {})
        stock_node = snapshot.get("stock_chip", {})
        if m == "tw":
            market_core_missing = (
                market_node.get("market_pcr_volume") is None
                and market_node.get("market_pcr_oi") is None
                and market_node.get("foreign_futures_oi_net") is None
                and market_node.get("large_trader_pcr_top5") is None
            )
            inst = stock_node.get("institutional_spot", {})
            stock_core_missing = (
                inst.get("foreign_net_shares") is None
                and inst.get("investment_trust_net_shares") is None
                and inst.get("dealer_net_shares") is None
            )
        else:
            market_core_missing = (
                market_node.get("institutional_holding_pct") is None
                and market_node.get("short_percent_of_float_pct") is None
            )
            holders = stock_node.get("institutional_holders", {})
            short_interest = stock_node.get("short_interest", {})
            stock_core_missing = (
                holders.get("held_percent_institutions") is None
                and short_interest.get("short_percent_of_float_pct") is None
            )

        degraded_mode = market_core_missing and stock_core_missing
        if degraded_mode:
            warnings.append(
                "核心籌碼欄位缺失，degraded_mode=true，結論應以 insufficient evidence 語氣呈現"
            )

        missing_fields: list[str] = []
        if market_core_missing:
            missing_fields.append("chip_snapshot.market_chip.core")
        if stock_core_missing:
            missing_fields.append("chip_snapshot.stock_chip.core")

        bundle = {
            "schema_version": "chip.bundle.v1",
            "instrument": {
                "ticker": ticker,
                "resolved_symbol": ticker_canonical,
                "market": m,
            },
            "analysis_date": analysis_date.isoformat(),
            "chip_snapshot": snapshot,
            "signal_summary": signals,
            "data_quality": {
                "warnings": sorted(set(warnings)),
                "degraded_mode": degraded_mode,
                "missing_fields": missing_fields,
                "staleness_days": _snapshot_staleness_days(manifest, analysis_date),
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

        required_after = ["market_chip", "stock_chip"]
        fresh_after = {
            ds: _dataset_is_fresh(manifest, ds, analysis_date) for ds in required_after
        }

        payload = {
            "ok": True,
            "ticker": ticker,
            "resolved_symbol": ticker_canonical,
            "market": m,
            "analysis_date": analysis_date.isoformat(),
            "schema_version": "chip.bundle.v1",
            "cache": {
                "bundle_file": str(paths["bundle"].relative_to(_PROJECT_ROOT)),
                "manifest_file": str(paths["manifest"].relative_to(_PROJECT_ROOT)),
                "cache_hit": False,
                "force_refresh": force_refresh,
                "fresh_map_before": fresh_map,
                "fresh_map_after": fresh_after,
            },
            "chip_snapshot": bundle["chip_snapshot"],
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


chip_analyst = Agent(
    model="gemini-2.5-flash",
    name="chip_analyst",
    description="籌碼分析師：分析大盤與個股參與者結構，輸出可核對數值的 chip_report。",
    tools=[get_chip_data],
    output_key="chip_report",
    instruction="""你是 AlphaCouncil 的籌碼分析師。

## 任務規則

1) 先呼叫一次 `get_chip_data(ticker, date, market, force_refresh=False)`；若未提供 `date` 或 `market`，預設為今日（Asia/Taipei）與 `tw`。
2) 僅使用工具回傳資料撰寫報告，禁止捏造數值。
3) 若 `ok=false`，直接回報資料錯誤與可能原因，不要硬做結論。
4) 若 `data_quality.degraded_mode=true`，必須以「insufficient evidence」語氣呈現，禁止硬下方向性結論。
5) 若 `data_quality.warnings` 非空，必須在「風險提示」完整揭露。

## 職責邊界

- 只做籌碼：大盤衍生品 baseline、法人現貨、融資融券、short interest、持股結構。
- 不得混入 MA/MACD/RSI/KD 等技術指標（歸 Technical Analyst）。
- 不得混入 VIX、恐慌或風險偏好敘述（歸 Psychology Analyst）。
- 不得混入新聞語氣與事件解讀（歸 News Analyst）。
- 不得混入估值、EPS、ROE 等基本面（歸 Fundamentals Analyst）。

## 輸出格式（固定）

### 籌碼分析師報告

**分析日期**：<analysis_date>
**標的**：<ticker / resolved_symbol>
**市場**：<market>

#### 摘要
- 3 條最重要結論（優先引用 `signal_summary`）

#### 大盤籌碼
- TW：引用 market_pcr_volume / market_pcr_oi（市場 baseline）與 foreign_futures_oi_net、large_trader_pcr_top5
- US：引用 market proxy（institutional_holding_pct、short_percent_of_float_pct）

#### 個股籌碼
- TW：引用 foreign/investment_trust/dealer/total net shares
- US：引用 held_percent_institutions、short_percent_of_float_pct、shares_short

#### 槓桿與放空壓力
- TW：引用 margin_balance_shares、short_balance_shares、short_to_margin_ratio、borrow_short_sell_shares
- US：引用 short_percent_of_float_pct / sharesPercentSharesOut（若有）

#### 風險提示
- 條列 `signal_summary.risk_flags`
- 揭露 `data_quality.warnings` 與 `degraded_mode`
- 說明資料缺口（例如 continuity_days、borrow_short_sell、warrant proxy）

最後加註：本報告僅供研究，不構成投資建議。
""",
)
