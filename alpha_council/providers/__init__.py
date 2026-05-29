"""Data provider layer — shared, master-agnostic access to fundamentals.

A `DataProvider` exposes the six functions used across master scoring modules:
get_financial_metrics, search_line_items, get_market_cap, get_insider_trades,
get_company_news, get_prices. Implementations:

  - YFinanceProvider  -- free, covers US fully and TW partially
  - MopsProvider      -- TW-only, fills yfinance gaps via 公開資訊觀測站
  - CompositeProvider -- routes by market and merges results

The default provider used by the pipeline is CompositeProvider; masters never
import a concrete implementation directly so the free-tier / full-tier swap
stays a single-line change.
"""
from alpha_council.providers.base import (
    CompanyNews,
    DataProvider,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    PriceBar,
)
from alpha_council.providers.composite import CompositeProvider, default_provider
from alpha_council.providers.mops_provider import MopsProvider
from alpha_council.providers.yfinance_provider import YFinanceProvider

__all__ = [
    "CompanyNews",
    "CompositeProvider",
    "DataProvider",
    "FinancialMetrics",
    "InsiderTrade",
    "LineItem",
    "MopsProvider",
    "PriceBar",
    "YFinanceProvider",
    "default_provider",
]
