"""Pipeline-level snapshot — fetch every shared provider call exactly once.

Why this module exists: master scoring rules call get_financial_metrics()
etc. directly; without a shared snapshot, 13 masters would issue 13 × 6
provider calls per run. With it, the first scoring call inside any master
populates session state, and the other 12 read from the same dict.

State layout (all keys prefixed with `shared_data:` to avoid collisions
with the existing string-keyed report state):

    shared_data:ticker            -> str (resolved input, e.g. "2330")
    shared_data:market            -> "us" | "tw"
    shared_data:financial_metrics -> list[FinancialMetrics] (annual)
    shared_data:line_items        -> list[LineItem]
    shared_data:market_cap        -> float | None
    shared_data:insider_trades    -> list[InsiderTrade]
    shared_data:company_news      -> list[CompanyNews]
    shared_data:prices            -> list[PriceBar] (1y daily)
    shared_data:fetched_at        -> ISO datetime

`SharedDataSnapshotAgent` is a no-LLM BaseAgent that runs once per pipeline
turn between master_selector and masters_panel. It is a no-op when
analysis_intent=False or awaiting_master_choice=True, mirroring the other
pre-master gates.

Scoring helpers call `ensure_snapshot(state)` defensively in case the
agent failed silently or the pipeline order changes; it is idempotent.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from typing_extensions import override

from alpha_council.providers import default_provider
from alpha_council.providers.base import CANONICAL_LINE_ITEMS, Market

logger = logging.getLogger(__name__)

# Same regexes used by market_snapshot._parse_ticker_from_state.
_TICKER_PATTERN = re.compile(r"\*{0,2}標的\*{0,2}\s*[：:]\s*([0-9A-Za-z][\w\.]*)")
_MARKET_PATTERN = re.compile(r"\*{0,2}市場\*{0,2}\s*[：:]\s*(tw|us|TW|US)")


def _parse_ticker_market(state) -> tuple[str, Market] | None:
    for key in ("technical_report", "fundamentals_report", "chip_report",
                "psychology_report", "news_report"):
        report = state.get(key, "") if hasattr(state, "get") else ""
        if not report:
            continue
        m = _TICKER_PATTERN.search(report)
        if not m:
            continue
        ticker = m.group(1).strip()
        market_match = _MARKET_PATTERN.search(report)
        market = market_match.group(1).lower() if market_match else "tw"
        return ticker, market  # type: ignore[return-value]
    return None


def ensure_snapshot(state) -> bool:
    """Idempotently populate shared_data:* in state. Returns True on hit/fill,
    False when ticker couldn't be resolved.
    """
    if state.get("shared_data:fetched_at"):
        return True
    parsed = _parse_ticker_market(state)
    if parsed is None:
        logger.info("ensure_snapshot: ticker not yet derivable from state -- skipping.")
        return False
    ticker, market = parsed
    provider = default_provider()
    logger.info("shared_data_snapshot: fetching for %s (%s) ...", ticker, market)

    state["shared_data:ticker"] = ticker
    state["shared_data:market"] = market

    try:
        state["shared_data:financial_metrics"] = provider.get_financial_metrics(
            ticker, market, limit=5, period="annual"
        )
    except Exception:
        logger.exception("shared_data: financial_metrics fetch failed.")
        state["shared_data:financial_metrics"] = []

    try:
        state["shared_data:line_items"] = provider.search_line_items(
            ticker,
            market,
            list(CANONICAL_LINE_ITEMS),
            limit=5,
            period="annual",
        )
    except Exception:
        logger.exception("shared_data: line_items fetch failed.")
        state["shared_data:line_items"] = []

    try:
        state["shared_data:market_cap"] = provider.get_market_cap(ticker, market)
    except Exception:
        logger.exception("shared_data: market_cap fetch failed.")
        state["shared_data:market_cap"] = None

    try:
        state["shared_data:insider_trades"] = provider.get_insider_trades(
            ticker, market, lookback_days=180
        )
    except Exception:
        logger.exception("shared_data: insider_trades fetch failed.")
        state["shared_data:insider_trades"] = []

    try:
        state["shared_data:company_news"] = provider.get_company_news(
            ticker, market, lookback_days=30, limit=20
        )
    except Exception:
        logger.exception("shared_data: company_news fetch failed.")
        state["shared_data:company_news"] = []

    try:
        state["shared_data:prices"] = provider.get_prices(ticker, market)
    except Exception:
        logger.exception("shared_data: prices fetch failed.")
        state["shared_data:prices"] = []

    state["shared_data:fetched_at"] = datetime.now(timezone.utc).isoformat()
    fm = state["shared_data:financial_metrics"]
    li = state["shared_data:line_items"]
    pr = state["shared_data:prices"]
    logger.info(
        "shared_data_snapshot: %s/%s done -- financial_metrics=%d, line_items=%d, prices=%d, market_cap=%s",
        ticker,
        market,
        len(fm),
        len(li),
        len(pr),
        state["shared_data:market_cap"],
    )
    return True


class SharedDataSnapshotAgent(BaseAgent):
    """No-LLM agent: populates session state with one set of provider results
    that every master scoring module reads from. Skips when masters won't run.
    """

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if state.get("analysis_intent") is False:
            logger.info("SharedDataSnapshotAgent: analysis_intent=False -- skipping.")
            return
        if state.get("awaiting_master_choice"):
            logger.info("SharedDataSnapshotAgent: awaiting_master_choice=True -- skipping.")
            return

        ensure_snapshot(state)
        # Returning without yielding events is intentional: this agent only
        # mutates state, so producing an Event would just inflate the trace.
        return
        yield  # noqa: needed to mark function as async generator
