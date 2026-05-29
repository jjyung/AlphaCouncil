"""Routing layer — combines YFinance and MOPS into one DataProvider.

The routing rule is per-method, not per-market: yfinance is always tried
first, and MOPS only fills in fields it is strictly better at (TW insider,
TW monthly revenue). This way the call sites in masters/_scoring don't need
to know which backend supplied which row.

For methods that yfinance handles fully (prices, market_cap, financial
metrics), MOPS is not even consulted — `MopsProvider` returns empty for
those by design, but skipping the call entirely also avoids extra HTTP.
"""
from __future__ import annotations

from datetime import date

from alpha_council.providers.base import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Market,
    PeriodKind,
    PriceBar,
)
from alpha_council.providers.mops_provider import MopsProvider
from alpha_council.providers.yfinance_provider import YFinanceProvider


class CompositeProvider:
    name = "composite"

    def __init__(
        self,
        yfinance: YFinanceProvider | None = None,
        mops: MopsProvider | None = None,
    ) -> None:
        self.yf = yfinance or YFinanceProvider()
        self.mops = mops or MopsProvider()

    # ----------------------- financial_metrics ------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        market: Market,
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[FinancialMetrics]:
        return self.yf.get_financial_metrics(ticker, market, end_date, limit, period)

    # ------------------------- line items -----------------------------

    def search_line_items(
        self,
        ticker: str,
        market: Market,
        line_items: list[str],
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[LineItem]:
        yf_items = self.yf.search_line_items(ticker, market, line_items, end_date, limit, period)
        # For TW + quarterly revenue, merge MOPS monthly revenue rows. They
        # share the same `name="revenue"` but newer period_ends — masters that
        # want freshness pick the head; ones that want quarterly comparability
        # filter by period_end alignment themselves.
        if market == "tw" and "revenue" in line_items and period == "quarterly":
            mops_items = self.mops.search_line_items(ticker, market, line_items, end_date, limit, period)
            seen: set[tuple[str, date]] = {(li.name, li.period_end) for li in yf_items}
            for item in mops_items:
                if (item.name, item.period_end) not in seen:
                    yf_items.append(item)
            yf_items.sort(key=lambda li: (li.name, li.period_end), reverse=True)
        return yf_items

    # ------------------------- market cap ----------------------------

    def get_market_cap(self, ticker: str, market: Market) -> float | None:
        return self.yf.get_market_cap(ticker, market)

    # ----------------------- insider trades --------------------------

    def get_insider_trades(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 180,
    ) -> list[InsiderTrade]:
        if market == "us":
            return self.yf.get_insider_trades(ticker, market, lookback_days)
        return self.mops.get_insider_trades(ticker, market, lookback_days)

    # ---------------------------- news -------------------------------

    def get_company_news(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 30,
        limit: int = 20,
    ) -> list[CompanyNews]:
        yf_news = self.yf.get_company_news(ticker, market, lookback_days, limit)
        if market != "tw":
            return yf_news
        # TW: layer TWSE 重大訊息 (structured catalysts) on top of any RSS hits.
        mops_news = self.mops.get_company_news(ticker, market, lookback_days, limit)
        merged = list(yf_news) + list(mops_news)
        merged.sort(key=lambda n: n.published_at, reverse=True)
        # de-dup by (title, date) since 重大訊息 and 新聞 sometimes overlap on title.
        seen: set[tuple[str, str]] = set()
        deduped: list[CompanyNews] = []
        for n in merged:
            key = (n.title.strip(), n.published_at.date().isoformat())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(n)
        return deduped[:limit]

    # --------------------------- prices ------------------------------

    def get_prices(
        self,
        ticker: str,
        market: Market,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[PriceBar]:
        return self.yf.get_prices(ticker, market, start_date, end_date)


_default: CompositeProvider | None = None


def default_provider() -> CompositeProvider:
    """Process-wide singleton. Masters / snapshot use this; tests can pass
    a fresh CompositeProvider into call sites instead.
    """
    global _default
    if _default is None:
        _default = CompositeProvider()
    return _default
