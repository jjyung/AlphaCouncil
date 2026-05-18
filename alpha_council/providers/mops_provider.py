"""TW-only backend — fills yfinance gaps via 公開資訊觀測站 / TWSE OpenAPI.

Scope is deliberately narrow: only methods where yfinance is empty/weak for
.TW symbols. Everything else returns an empty list, and CompositeProvider
falls back to yfinance.

Endpoints used (all public JSON, no auth):
  - 月營收:           https://openapi.twse.com.tw/v1/opendata/t187ap05_L
  - 重大訊息:         https://openapi.twse.com.tw/v1/opendata/t187ap04_L
  - 董監事持股餘額:    https://openapi.twse.com.tw/v1/opendata/t187ap11_L
  - 預定轉讓申報:      https://openapi.twse.com.tw/v1/opendata/t187ap12_L

Why TWSE OpenAPI instead of raw MOPS form-posts: the OpenAPI returns JSON,
has no anti-bot, and ships under terms permitting cached redistribution.
MOPS form-posts are gated by an IP/session anti-bot layer that returns a
"頁面無法執行" stub without a real browser session, so we route around them.

Insider trades for TW are *approximated* — the OpenAPI does not expose a
per-trade ledger. Two structured signals are combined into one synthetic
list of `InsiderTrade` rows:

  1. From `t187ap11_L`: for each director / supervisor, `目前持股` minus
     `選任時持股` is the cumulative net buy/sell since they took office.
     One row per insider per snapshot, `transaction_type="buy"|"sell"`,
     `shares=delta`. This is what feeds Buffett's "insider net buying"
     criterion. NB: it is a *stock* not a *flow* — the same delta will
     re-appear every month until the next election cycle.
  2. From `t187ap12_L`: each planned-transfer pre-filing becomes a
     `transaction_type="planned_sell"` row. Forward-looking sell signal.

Per-process cache (`_endpoint_cache`) holds the full opendata payload for
~6 hours since these datasets update on monthly/event cadence, not by the
minute. Sharing across tickers is the point: one fetch serves the entire
masters panel for any TW symbol in the same dataset.

If an endpoint shape drifts (TWSE has changed field names before), the
parser logs a structured warning and returns empty for that ticker rather
than crashing the pipeline.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from alpha_council.providers.base import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Market,
    PeriodKind,
    PriceBar,
)

logger = logging.getLogger(__name__)

_OPENAPI_MONTHLY_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
_OPENAPI_MATERIAL_NEWS = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
_OPENAPI_DIRECTOR_HOLDINGS = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
_OPENAPI_PLANNED_TRANSFER = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"

_CACHE_TTL_SECONDS = 6 * 3600

# value: (fetched_at_epoch, payload)
_endpoint_cache: dict[str, tuple[float, list[dict]]] = {}


def _normalise_ticker(ticker: str) -> str:
    """TW endpoints index by bare digit code (e.g. '2330'), not '.TW' suffix."""
    t = ticker.strip().upper()
    if t.endswith(".TW") or t.endswith(".TWO"):
        return t.rsplit(".", 1)[0]
    return t


def _fetch_endpoint(url: str, *, timeout: float = 8.0) -> list[dict] | None:
    cached = _endpoint_cache.get(url)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "alpha-council/0.1"})
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("TWSE OpenAPI fetch failed for %s: %s", url, exc)
        return None
    except ValueError as exc:
        logger.warning("TWSE OpenAPI JSON decode failed for %s: %s", url, exc)
        return None
    if not isinstance(payload, list):
        logger.warning("TWSE OpenAPI %s returned non-list payload (type=%s)", url, type(payload).__name__)
        return None
    _endpoint_cache[url] = (now, payload)
    return payload


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None


def _parse_date_yyymmdd(s: str) -> date | None:
    """ROC date format (e.g. '1130315') → 2024-03-15."""
    if not s:
        return None
    raw = str(s).strip()
    if not raw.isdigit():
        return None
    if len(raw) == 7:
        roc_year = int(raw[:3])
        month = int(raw[3:5])
        day = int(raw[5:7])
        try:
            return date(roc_year + 1911, month, day)
        except ValueError:
            return None
    if len(raw) == 8:  # already AD
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None
    return None


class MopsProvider:
    """TW-only fundamentals + insider via TWSE OpenAPI."""

    name = "twse_openapi"

    # ----------- methods yfinance covers better -----------

    def get_financial_metrics(self, *a, **kw) -> list[FinancialMetrics]:
        return []

    def get_market_cap(self, *a, **kw) -> float | None:
        return None

    def get_prices(self, *a, **kw) -> list[PriceBar]:
        return []

    def get_company_news(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 30,
        limit: int = 20,
    ) -> list[CompanyNews]:
        """TW 重大訊息 from TWSE OpenAPI.

        These are MOPS material-event filings (取得處分資產、董事會決議、財報更新等),
        not press releases. They are structured catalyst signals — useful for
        Buffett-style "narrative risk" and Burry-style "event-driven" reads.
        Press releases continue to flow through news_analyst's RSS pipeline.
        """
        if market != "tw":
            return []
        payload = _fetch_endpoint(_OPENAPI_MATERIAL_NEWS)
        if payload is None:
            return []
        code = _normalise_ticker(ticker)
        cutoff = date.today() - timedelta(days=lookback_days)
        results: list[CompanyNews] = []
        for r in payload:
            if str(r.get("公司代號", "")).strip() != code:
                continue
            pub_date = _parse_date_yyymmdd(r.get("發言日期") or r.get("出表日期") or "")
            if pub_date is None or pub_date < cutoff:
                continue
            results.append(
                CompanyNews(
                    ticker=code,
                    published_at=datetime(pub_date.year, pub_date.month, pub_date.day, tzinfo=timezone.utc),
                    title=str(r.get("主旨") or r.get("主旨 ") or "").strip(),
                    url=None,
                    publisher="TWSE 公開資訊觀測站",
                    summary=str(r.get("說明") or "").strip()[:500] or None,
                    source=self.name,
                )
            )
        results.sort(key=lambda n: n.published_at, reverse=True)
        return results[:limit]

    # ----------- 月營收 → revenue line items -----------

    def search_line_items(
        self,
        ticker: str,
        market: Market,
        line_items: list[str],
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[LineItem]:
        if market != "tw" or "revenue" not in line_items or period != "quarterly":
            # yfinance covers annual+quarterly statements; we only add the
            # monthly granularity that yfinance lacks.
            return []
        return self._monthly_revenue_as_items(ticker, end_date=end_date, limit=limit)

    def get_monthly_revenue(
        self,
        ticker: str,
        end_date: date | None = None,
        limit: int = 13,
    ) -> list[LineItem]:
        """TW-specific helper: return up to `limit` most recent monthly revenue rows.

        This is the headline gap yfinance has for TW — quarterly statements
        only update 4 times a year, but listed firms file monthly revenue by
        the 10th of every month, giving a much fresher signal.
        """
        return self._monthly_revenue_as_items(ticker, end_date=end_date, limit=limit)

    def _monthly_revenue_as_items(
        self,
        ticker: str,
        *,
        end_date: date | None,
        limit: int,
    ) -> list[LineItem]:
        code = _normalise_ticker(ticker)
        payload = _fetch_endpoint(_OPENAPI_MONTHLY_REVENUE)
        if payload is None:
            return []
        # The opendata snapshot is for a single month: filter by company code,
        # then there is exactly one row. To get history, we rely on yfinance's
        # quarterly statement for trend; this single row is the freshest data
        # point not yet in any quarterly filing.
        rows = [r for r in payload if str(r.get("公司代號", "")).strip() == code]
        if not rows:
            logger.info("MopsProvider: no monthly revenue row for %s in latest dataset.", code)
            return []
        result: list[LineItem] = []
        for r in rows:
            year = _safe_int(r.get("資料年月", "0")[:3] if isinstance(r.get("資料年月"), str) else None)
            yyyymm = str(r.get("資料年月", "")).strip()
            period_end: date | None = None
            if len(yyyymm) >= 5 and yyyymm.isdigit():
                roc_year = int(yyyymm[:-2])
                month = int(yyyymm[-2:])
                try:
                    # End-of-month approximation; exact day doesn't matter for
                    # scoring rules that just want time-ordered values.
                    period_end = (date(roc_year + 1911, month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                except ValueError:
                    period_end = None
            if period_end is None:
                continue
            if end_date is not None and period_end > end_date:
                continue
            revenue = _safe_float(r.get("營業收入-當月營收"))
            result.append(
                LineItem(
                    ticker=code,
                    period_end=period_end,
                    period="quarterly",  # monthly cadence reported under quarterly slot
                    name="revenue",
                    value=revenue,
                    currency="TWD",
                    source=self.name,
                )
            )
        result.sort(key=lambda li: li.period_end, reverse=True)
        return result[:limit]

    # ----------- 內部人持股變動 -----------

    def get_insider_trades(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 180,
    ) -> list[InsiderTrade]:
        """Synthesise insider trades from two TWSE OpenAPI endpoints.

        The `lookback_days` parameter is honoured only on the planned-
        transfer rows (those have real dates). Since-election deltas from
        t187ap11_L carry the snapshot 資料年月 as their transaction date,
        which lookback typically retains because the snapshot is monthly.

        Returns may include `transaction_type` values not seen in US
        insider data: "planned_sell" (announced future transfer). Buffett
        scoring treats "buy" as positive and any "sell"/"planned_sell"
        as negative; other masters can filter on the type directly.
        """
        if market != "tw":
            return []
        code = _normalise_ticker(ticker)
        cutoff = date.today() - timedelta(days=lookback_days)
        results: list[InsiderTrade] = []

        holdings = _fetch_endpoint(_OPENAPI_DIRECTOR_HOLDINGS)
        if holdings is not None:
            results.extend(self._extract_since_election_deltas(holdings, code, cutoff))

        planned = _fetch_endpoint(_OPENAPI_PLANNED_TRANSFER)
        if planned is not None:
            results.extend(self._extract_planned_transfers(planned, code, cutoff))

        return results

    def _extract_since_election_deltas(
        self,
        payload: list[dict],
        code: str,
        cutoff: date,
    ) -> list[InsiderTrade]:
        """Build per-insider rows, deduped by (姓名, 目前持股).

        TWSE files the same officer once per role they hold (e.g. someone
        serving as both 副總經理 and 財務部門主管 appears twice with identical
        holdings). Without dedupe the net delta double-counts. We also drop
        rows where 選任時持股=0 — that flag means the officer was promoted
        into the role without re-electing, so the "since-election" delta is
        not interpretable for them and would otherwise overstate buying.
        """
        seen: dict[tuple[str, float], InsiderTrade] = {}
        for r in payload:
            if str(r.get("公司代號", "")).strip() != code:
                continue
            yyyymm = str(r.get("資料年月", "")).strip()
            tx_date: date | None = None
            if len(yyyymm) >= 5 and yyyymm.isdigit():
                roc_year = int(yyyymm[:-2])
                month = int(yyyymm[-2:])
                try:
                    tx_date = (date(roc_year + 1911, month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                except ValueError:
                    tx_date = None
            if tx_date is None or tx_date < cutoff:
                continue
            current = _safe_float(r.get("目前持股"))
            elected = _safe_float(r.get("選任時持股") or r.get("選任時持股 "))
            if current is None or elected is None or elected == 0:
                continue
            delta = current - elected
            if delta == 0:
                continue
            name = str(r.get("姓名") or "").strip()
            if not name:
                continue
            key = (name, current)
            if key in seen:
                continue
            tx_type = "buy" if delta > 0 else "sell"
            seen[key] = InsiderTrade(
                ticker=code,
                transaction_date=tx_date,
                insider_name=name,
                title=str(r.get("職稱") or "").strip() or None,
                transaction_type=tx_type,
                shares=delta,
                price=None,
                value=None,
                source=self.name,
            )
        return list(seen.values())

    def _extract_planned_transfers(
        self,
        payload: list[dict],
        code: str,
        cutoff: date,
    ) -> list[InsiderTrade]:
        out: list[InsiderTrade] = []
        for r in payload:
            if str(r.get("公司代號", "")).strip() != code:
                continue
            tx_date = _parse_date_yyymmdd(r.get("出表日期") or "")
            if tx_date is None or tx_date < cutoff:
                continue
            planned_self = _safe_float(r.get("預定轉讓總股數-自有持股")) or 0
            planned_trust = _safe_float(r.get("預定轉讓總股數-保留運用決定權信託股數")) or 0
            planned_total = planned_self + planned_trust
            if planned_total <= 0:
                continue
            out.append(
                InsiderTrade(
                    ticker=code,
                    transaction_date=tx_date,
                    insider_name=str(r.get("姓名") or "").strip() or None,
                    title=str(r.get("申報人身分") or "").strip() or None,
                    transaction_type="planned_sell",
                    shares=-planned_total,  # negative to align with sell convention
                    price=None,
                    value=None,
                    source=self.name,
                )
            )
        return out
