"""YFinance backend — covers US fully and TW partially.

What works:
  - get_prices: solid for both markets.
  - get_financial_metrics / search_line_items: works for both; TW depth is
    capped at ~4 annual + ~5 quarterly periods.
  - get_market_cap: works for both.

What is weak for TW (delegated to MopsProvider via CompositeProvider):
  - get_insider_trades: yfinance returns empty for .TW symbols.
  - get_company_news: yfinance returns very few or zero items for .TW.
  - 月營收: not in yfinance at all; only quarterly granularity is exposed.

`_row()` is the heart of line-item extraction: yfinance's row labels are not
stable across versions or markets, so we lookup each canonical name against a
list of label aliases. Every alias miss is logged once — when scoring starts
returning "criterion unverified" too often, the log tells us which alias list
needs an addition rather than us re-reading the raw DataFrame.

A per-process Ticker cache (`_ticker_cache`) avoids re-hitting yfinance for
the same symbol from different methods within a pipeline run. The shared
snapshot in utils/shared_data_snapshot.py caches the *results* (dataclass
lists) on top, so the same call from 13 masters costs one network round-trip.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

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

_ticker_cache: dict[str, yf.Ticker] = {}
_missing_label_logged: set[str] = set()


# ---------------------------------------------------------------------------
# Symbol resolution
# ---------------------------------------------------------------------------


def _tw_candidates(ticker: str) -> list[str]:
    t = ticker.strip().upper()
    if t.endswith(".TW") or t.endswith(".TWO"):
        return [t]
    if t.isdigit():
        return [f"{t}.TW", f"{t}.TWO"]
    return [t]


def _resolve_symbol(ticker: str, market: Market) -> str | None:
    """Return the first yfinance symbol that returns non-empty history.

    Result is memoised in `_ticker_cache` keyed by the *resolved* symbol;
    the input ticker may map to different symbols (e.g. 2330 → 2330.TW).
    """
    candidates = [ticker.strip().upper()] if market == "us" else _tw_candidates(ticker)
    for symbol in candidates:
        cached = _ticker_cache.get(symbol)
        if cached is not None:
            return symbol
        try:
            tk = yf.Ticker(symbol)
            hist = tk.history(period="5d", auto_adjust=False)
            if hist is not None and not hist.empty:
                _ticker_cache[symbol] = tk
                return symbol
        except Exception as exc:  # noqa: BLE001
            logger.debug("yfinance probe %s failed: %s", symbol, exc)
    return None


def _ticker(ticker: str, market: Market) -> tuple[yf.Ticker | None, str | None]:
    symbol = _resolve_symbol(ticker, market)
    if symbol is None:
        return None, None
    return _ticker_cache[symbol], symbol


# ---------------------------------------------------------------------------
# DataFrame row aliases — yfinance labels vary across versions and markets.
# ---------------------------------------------------------------------------

_INCOME_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Revenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income", "Operating Income Loss"),
    "net_income": (
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
    ),
    "research_and_development": ("Research And Development",),
    "earnings_per_share": ("Basic EPS", "Diluted EPS"),
}

_BALANCE_ALIASES: dict[str, tuple[str, ...]] = {
    "total_assets": ("Total Assets",),
    "total_equity": (
        "Stockholders Equity",
        "Total Equity Gross Minority Interest",
        "Common Stock Equity",
    ),
    "total_debt": ("Total Debt", "Net Debt"),
    "current_assets": ("Current Assets",),
    "current_liabilities": ("Current Liabilities",),
    "cash_and_equivalents": (
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ),
    "shares_outstanding": (
        "Ordinary Shares Number",
        "Share Issued",
    ),
    "long_term_debt": ("Long Term Debt",),
    "invested_capital": ("Invested Capital",),
}

_CASHFLOW_ALIASES: dict[str, tuple[str, ...]] = {
    "operating_cash_flow": ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
    "free_cash_flow": ("Free Cash Flow",),
    "capital_expenditure": ("Capital Expenditure", "Capital Expenditures"),
    "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
}


def _row(df: pd.DataFrame, aliases: Iterable[str], canonical: str) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for alias in aliases:
        if alias in df.index:
            return df.loc[alias]
    key = f"{canonical}::{tuple(df.index[:3])}"
    if key not in _missing_label_logged:
        _missing_label_logged.add(key)
        logger.info(
            "yfinance label miss: %r not in df (first 3 rows: %s)",
            canonical,
            list(df.index[:3]),
        )
    return None


def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _col_date(col) -> date:
    """yfinance financial DataFrames use Timestamp or str columns for period_end."""
    if isinstance(col, pd.Timestamp):
        return col.date()
    if isinstance(col, date):
        return col
    try:
        return pd.Timestamp(col).date()
    except Exception:  # noqa: BLE001
        return date.today()


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class YFinanceProvider:
    name = "yfinance"

    # ------------------------- financial metrics -------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        market: Market,
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[FinancialMetrics]:
        tk, symbol = _ticker(ticker, market)
        if tk is None:
            return []
        quarterly = period == "quarterly"
        try:
            inc = tk.quarterly_financials if quarterly else tk.financials
            bal = tk.quarterly_balance_sheet if quarterly else tk.balance_sheet
            cfs = tk.quarterly_cashflow if quarterly else tk.cashflow
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance fundamentals fetch failed for %s: %s", symbol, exc)
            return []

        info = self._safe_info(tk)
        results: list[FinancialMetrics] = []
        if inc is None or inc.empty:
            return results

        revenue_row = _row(inc, _INCOME_ALIASES["revenue"], "revenue")
        net_income_row = _row(inc, _INCOME_ALIASES["net_income"], "net_income")
        op_income_row = _row(inc, _INCOME_ALIASES["operating_income"], "operating_income")
        gross_row = _row(inc, _INCOME_ALIASES["gross_profit"], "gross_profit")
        eps_row = _row(inc, _INCOME_ALIASES["earnings_per_share"], "earnings_per_share")

        equity_row = _row(bal, _BALANCE_ALIASES["total_equity"], "total_equity")
        debt_row = _row(bal, _BALANCE_ALIASES["total_debt"], "total_debt")
        assets_row = _row(bal, _BALANCE_ALIASES["total_assets"], "total_assets")
        ca_row = _row(bal, _BALANCE_ALIASES["current_assets"], "current_assets")
        cl_row = _row(bal, _BALANCE_ALIASES["current_liabilities"], "current_liabilities")
        cash_row = _row(bal, _BALANCE_ALIASES["cash_and_equivalents"], "cash_and_equivalents")
        shares_row = _row(bal, _BALANCE_ALIASES["shares_outstanding"], "shares_outstanding")
        invested_row = _row(bal, _BALANCE_ALIASES["invested_capital"], "invested_capital")

        fcf_row = _row(cfs, _CASHFLOW_ALIASES["free_cash_flow"], "free_cash_flow")

        period_ends = list(inc.columns)
        if end_date is not None:
            period_ends = [c for c in period_ends if _col_date(c) <= end_date]
        period_ends = period_ends[:limit]

        # Sort newest first so YoY math indexes correctly.
        period_ends.sort(key=_col_date, reverse=True)

        for i, col in enumerate(period_ends):
            d = _col_date(col)
            revenue = _safe(revenue_row[col]) if revenue_row is not None else None
            net_income = _safe(net_income_row[col]) if net_income_row is not None else None
            op_income = _safe(op_income_row[col]) if op_income_row is not None else None
            gross = _safe(gross_row[col]) if gross_row is not None else None
            eps = _safe(eps_row[col]) if eps_row is not None else None

            equity = _safe(equity_row[col]) if equity_row is not None else None
            debt = _safe(debt_row[col]) if debt_row is not None else None
            assets = _safe(assets_row[col]) if assets_row is not None else None
            ca = _safe(ca_row[col]) if ca_row is not None else None
            cl = _safe(cl_row[col]) if cl_row is not None else None
            shares = _safe(shares_row[col]) if shares_row is not None else None
            invested = _safe(invested_row[col]) if invested_row is not None else None

            fcf = _safe(fcf_row[col]) if fcf_row is not None else None

            # Derive ratios when both inputs exist.
            def _ratio(num: float | None, den: float | None) -> float | None:
                if num is None or den is None or den == 0:
                    return None
                return num / den

            roe = _ratio(net_income, equity)
            roa = _ratio(net_income, assets)
            roic = _ratio(net_income, invested) if invested is not None else None
            d_e = _ratio(debt, equity)
            cur_ratio = _ratio(ca, cl)
            gross_margin = _ratio(gross, revenue)
            op_margin = _ratio(op_income, revenue)
            net_margin = _ratio(net_income, revenue)
            bvps = _ratio(equity, shares)

            # YoY growth needs the previous period from this same list.
            prior_col = period_ends[i + 1] if i + 1 < len(period_ends) else None
            rev_growth: float | None = None
            earn_growth: float | None = None
            if prior_col is not None:
                prev_rev = _safe(revenue_row[prior_col]) if revenue_row is not None else None
                prev_ni = _safe(net_income_row[prior_col]) if net_income_row is not None else None
                rev_growth = _ratio((revenue or 0) - (prev_rev or 0), prev_rev) if prev_rev else None
                earn_growth = _ratio((net_income or 0) - (prev_ni or 0), abs(prev_ni)) if prev_ni else None

            results.append(
                FinancialMetrics(
                    ticker=symbol or ticker,
                    period_end=d,
                    period="quarterly" if quarterly else "annual",
                    revenue=revenue,
                    net_income=net_income,
                    operating_income=op_income,
                    gross_margin=gross_margin,
                    operating_margin=op_margin,
                    net_margin=net_margin,
                    return_on_equity=roe,
                    return_on_invested_capital=roic,
                    return_on_assets=roa,
                    debt_to_equity=d_e,
                    current_ratio=cur_ratio,
                    quick_ratio=None,
                    revenue_growth_yoy=rev_growth,
                    earnings_growth_yoy=earn_growth,
                    book_value_per_share=bvps,
                    earnings_per_share=eps,
                    free_cash_flow=fcf,
                    source=self.name,
                )
            )

        # Newest period: backfill ratios from `info` if statement-derived values are missing.
        if results and info:
            head = results[0]
            patched = {
                "return_on_equity": head.return_on_equity if head.return_on_equity is not None else _safe(info.get("returnOnEquity")),
                "return_on_assets": head.return_on_assets if head.return_on_assets is not None else _safe(info.get("returnOnAssets")),
                "operating_margin": head.operating_margin if head.operating_margin is not None else _safe(info.get("operatingMargins")),
                "net_margin": head.net_margin if head.net_margin is not None else _safe(info.get("profitMargins")),
                "gross_margin": head.gross_margin if head.gross_margin is not None else _safe(info.get("grossMargins")),
                "current_ratio": head.current_ratio if head.current_ratio is not None else _safe(info.get("currentRatio")),
                "quick_ratio": _safe(info.get("quickRatio")),
                "debt_to_equity": head.debt_to_equity if head.debt_to_equity is not None else (
                    _safe(info.get("debtToEquity")) / 100 if _safe(info.get("debtToEquity")) is not None else None
                ),
                "revenue_growth_yoy": head.revenue_growth_yoy if head.revenue_growth_yoy is not None else _safe(info.get("revenueGrowth")),
                "earnings_growth_yoy": head.earnings_growth_yoy if head.earnings_growth_yoy is not None else _safe(info.get("earningsGrowth")),
            }
            results[0] = FinancialMetrics(
                ticker=head.ticker,
                period_end=head.period_end,
                period=head.period,
                revenue=head.revenue,
                net_income=head.net_income,
                operating_income=head.operating_income,
                book_value_per_share=head.book_value_per_share,
                earnings_per_share=head.earnings_per_share,
                free_cash_flow=head.free_cash_flow,
                source=head.source,
                **patched,
            )
        return results

    # --------------------------- line items -----------------------------

    def search_line_items(
        self,
        ticker: str,
        market: Market,
        line_items: list[str],
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[LineItem]:
        tk, symbol = _ticker(ticker, market)
        if tk is None:
            return []
        quarterly = period == "quarterly"
        try:
            inc = tk.quarterly_financials if quarterly else tk.financials
            bal = tk.quarterly_balance_sheet if quarterly else tk.balance_sheet
            cfs = tk.quarterly_cashflow if quarterly else tk.cashflow
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance line_items fetch failed for %s: %s", symbol, exc)
            return []

        results: list[LineItem] = []
        for name in line_items:
            if name in _INCOME_ALIASES:
                df, aliases = inc, _INCOME_ALIASES[name]
            elif name in _BALANCE_ALIASES:
                df, aliases = bal, _BALANCE_ALIASES[name]
            elif name in _CASHFLOW_ALIASES:
                df, aliases = cfs, _CASHFLOW_ALIASES[name]
            else:
                logger.info("Unknown canonical line item %r — skipping.", name)
                continue

            row = _row(df, aliases, name)
            if row is None:
                continue
            cols = list(row.index)
            if end_date is not None:
                cols = [c for c in cols if _col_date(c) <= end_date]
            cols.sort(key=_col_date, reverse=True)
            for col in cols[:limit]:
                results.append(
                    LineItem(
                        ticker=symbol or ticker,
                        period_end=_col_date(col),
                        period="quarterly" if quarterly else "annual",
                        name=name,
                        value=_safe(row[col]),
                        currency=None,
                        source=self.name,
                    )
                )
        return results

    # --------------------------- market cap -----------------------------

    def get_market_cap(self, ticker: str, market: Market) -> float | None:
        tk, _ = _ticker(ticker, market)
        if tk is None:
            return None
        info = self._safe_info(tk)
        return _safe(info.get("marketCap")) if info else None

    # ------------------------- insider trades ---------------------------

    def get_insider_trades(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 180,
    ) -> list[InsiderTrade]:
        # yfinance returns empty for TW symbols; let MopsProvider handle that.
        if market == "tw":
            return []
        tk, symbol = _ticker(ticker, market)
        if tk is None:
            return []
        try:
            df = tk.insider_transactions
        except Exception as exc:  # noqa: BLE001
            logger.debug("yfinance insider_transactions failed for %s: %s", symbol, exc)
            return []
        if df is None or df.empty:
            return []

        cutoff = date.today() - timedelta(days=lookback_days)
        results: list[InsiderTrade] = []
        for _, row in df.iterrows():
            raw_date = row.get("Start Date") or row.get("Date")
            try:
                d = pd.Timestamp(raw_date).date()
            except Exception:  # noqa: BLE001
                continue
            if d < cutoff:
                continue
            results.append(
                InsiderTrade(
                    ticker=symbol or ticker,
                    transaction_date=d,
                    insider_name=row.get("Insider"),
                    title=row.get("Position"),
                    transaction_type=str(row.get("Transaction") or "").lower(),
                    shares=_safe(row.get("Shares")),
                    price=None,
                    value=_safe(row.get("Value")),
                    source=self.name,
                )
            )
        return results

    # ---------------------------- news ---------------------------------

    def get_company_news(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 30,
        limit: int = 20,
    ) -> list[CompanyNews]:
        tk, symbol = _ticker(ticker, market)
        if tk is None:
            return []
        try:
            items = tk.news or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("yfinance news failed for %s: %s", symbol, exc)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        results: list[CompanyNews] = []
        for item in items[:limit]:
            content = item.get("content") if isinstance(item, dict) else None
            data = content or item
            ts = data.get("pubDate") or data.get("providerPublishTime")
            try:
                published = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if isinstance(ts, str)
                    else datetime.fromtimestamp(int(ts), tz=timezone.utc)
                )
            except Exception:  # noqa: BLE001
                published = datetime.now(timezone.utc)
            if published < cutoff:
                continue
            url = None
            click = data.get("clickThroughUrl") or data.get("canonicalUrl")
            if isinstance(click, dict):
                url = click.get("url")
            elif isinstance(click, str):
                url = click
            elif "link" in data:
                url = data["link"]
            results.append(
                CompanyNews(
                    ticker=symbol or ticker,
                    published_at=published,
                    title=str(data.get("title") or "").strip(),
                    url=url,
                    publisher=data.get("provider", {}).get("displayName") if isinstance(data.get("provider"), dict) else data.get("publisher"),
                    summary=data.get("summary"),
                    source=self.name,
                )
            )
        return results

    # --------------------------- prices --------------------------------

    def get_prices(
        self,
        ticker: str,
        market: Market,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[PriceBar]:
        tk, symbol = _ticker(ticker, market)
        if tk is None:
            return []
        kwargs: dict = {"auto_adjust": False}
        if start_date is not None:
            kwargs["start"] = start_date.isoformat()
        else:
            kwargs["period"] = "1y"
        if end_date is not None:
            kwargs["end"] = end_date.isoformat()
        try:
            df = tk.history(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance history failed for %s: %s", symbol, exc)
            return []
        if df is None or df.empty:
            return []

        results: list[PriceBar] = []
        for idx, row in df.iterrows():
            d = idx.date() if hasattr(idx, "date") else pd.Timestamp(idx).date()
            close = _safe(row.get("Close"))
            high = _safe(row.get("High"))
            low = _safe(row.get("Low"))
            open_ = _safe(row.get("Open"))
            if close is None or high is None or low is None or open_ is None:
                continue
            results.append(
                PriceBar(
                    ticker=symbol or ticker,
                    bar_date=d,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=_safe(row.get("Volume")),
                    adj_close=_safe(row.get("Adj Close")),
                    source=self.name,
                )
            )
        return results

    # --------------------------- helpers -------------------------------

    @staticmethod
    def _safe_info(tk: yf.Ticker) -> dict:
        try:
            info = tk.info or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("yfinance info() failed: %s", exc)
            info = {}
        return info if isinstance(info, dict) else {}
