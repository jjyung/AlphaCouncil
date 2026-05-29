"""Provider contracts — frozen dataclasses + Protocol shared by every backend.

The dataclasses are the canonical wire format between providers and master
scoring modules. They are intentionally minimal: only fields a scoring rule
might consult. Keep `period_end` as `date` (not str) so callers can sort /
diff without re-parsing.

`Market` is constrained to {"us", "tw"} — the rest of the codebase already
uses these two strings (see market_snapshot, technical_analyst). Extending it
later means adding both a literal and routing in CompositeProvider.

`search_line_items` takes a list of canonical names rather than every
balance-sheet row; YFinanceProvider maps those names to yfinance's column
labels and MopsProvider maps to its own row codes, isolating each backend's
schema quirks behind the same call site.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

Market = Literal["us", "tw"]
PeriodKind = Literal["annual", "quarterly", "ttm"]

CANONICAL_LINE_ITEMS: tuple[str, ...] = (
    "revenue",
    "operating_income",
    "net_income",
    "gross_profit",
    "free_cash_flow",
    "operating_cash_flow",
    "capital_expenditure",
    "total_debt",
    "total_equity",
    "total_assets",
    "current_assets",
    "current_liabilities",
    "cash_and_equivalents",
    "shares_outstanding",
    "dividends_paid",
    "research_and_development",
)


@dataclass(frozen=True)
class FinancialMetrics:
    """Period-end roll-up. One row per (ticker, period_end, period)."""

    ticker: str
    period_end: date
    period: PeriodKind
    revenue: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    return_on_equity: float | None = None
    return_on_invested_capital: float | None = None
    return_on_assets: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    book_value_per_share: float | None = None
    earnings_per_share: float | None = None
    free_cash_flow: float | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class LineItem:
    """Single fundamental data point, e.g. (FCF, 2024-12-31, 100M)."""

    ticker: str
    period_end: date
    period: PeriodKind
    name: str
    value: float | None
    currency: str | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class InsiderTrade:
    ticker: str
    transaction_date: date
    insider_name: str | None
    title: str | None
    transaction_type: str
    shares: float | None
    price: float | None
    value: float | None
    source: str = "unknown"


@dataclass(frozen=True)
class CompanyNews:
    ticker: str
    published_at: datetime
    title: str
    url: str | None = None
    publisher: str | None = None
    summary: str | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class PriceBar:
    ticker: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    adj_close: float | None = None
    source: str = "unknown"


class DataProvider(Protocol):
    """Six-function contract every backend implements.

    Methods must be side-effect free aside from caching, and must never raise
    on missing data — instead return an empty list (or None for market_cap).
    Callers rely on this to keep scoring rules total: a missing field becomes
    a "criterion unverified" outcome, not a pipeline crash.
    """

    def get_financial_metrics(
        self,
        ticker: str,
        market: Market,
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[FinancialMetrics]: ...

    def search_line_items(
        self,
        ticker: str,
        market: Market,
        line_items: list[str],
        end_date: date | None = None,
        limit: int = 5,
        period: PeriodKind = "annual",
    ) -> list[LineItem]: ...

    def get_market_cap(self, ticker: str, market: Market) -> float | None: ...

    def get_insider_trades(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 180,
    ) -> list[InsiderTrade]: ...

    def get_company_news(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 30,
        limit: int = 20,
    ) -> list[CompanyNews]: ...

    def get_prices(
        self,
        ticker: str,
        market: Market,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[PriceBar]: ...
