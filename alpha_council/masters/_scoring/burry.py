"""Michael Burry — deep value, contrarian, asset coverage above all.

Burry's process is mechanical at the screen level: cheap on tangible
metrics, beaten down by sentiment, with at least one structural reason
the consensus is wrong. The deterministic side covers the screen; the
"why is consensus wrong" thesis is left to the LLM persona because it
needs the analyst reports.

  Drawdown from 52w high (3)  price < 60% of high (3) | < 75% (2) | < 90% (1)
  NCAV / market cap (3)       > 1.0 net-net (3) | > 0.5 (2) | > 0.2 (1)
                              NCAV ≈ current_assets − total_liabilities
                              (TL ≈ total_assets − total_equity)
  P/B (book yield) (2)        equity/mcap > 1.0 (2) | > 0.5 (1)
  Contrarian insider buy (2)  drawdown > 20% AND insider net buying (2) |
                              insider net buying alone (1)

Total cap 10. Burry famously layers in a *catalyst* (e.g. structural
mortgage view); we can't observe that — relay it via the LLM persona.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from alpha_council.masters._scoring.common import (
    ScoreLine,
    format_scorecard,
    latest,
    line_item_series,
    money,
    num,
    pct,
)
from alpha_council.providers.base import (
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    PriceBar,
)


@dataclass(frozen=True)
class BurryScore:
    drawdown: list[ScoreLine] = field(default_factory=list)
    ncav: list[ScoreLine] = field(default_factory=list)
    pb: list[ScoreLine] = field(default_factory=list)
    contrarian_signal: list[ScoreLine] = field(default_factory=list)
    current_price: float | None = None
    high_52w: float | None = None
    drawdown_pct: float | None = None
    ncav_value: float | None = None
    market_cap: float | None = None

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (self.drawdown, self.ncav, self.pb, self.contrarian_signal)


def _drawdown(prices: list[PriceBar]) -> tuple[list[ScoreLine], float | None, float | None, float | None]:
    if not prices:
        return ([ScoreLine("Drawdown from 52w high", 0.0, 3.0, "no price history")], None, None, None)
    closes = [p.close for p in prices if p.close is not None]
    if not closes:
        return ([ScoreLine("Drawdown from 52w high", 0.0, 3.0, "no closes")], None, None, None)
    high = max(closes)
    current = prices[-1].close
    if current is None or high <= 0:
        return ([ScoreLine("Drawdown from 52w high", 0.0, 3.0, "current or high invalid")],
                current, high, None)
    ratio = current / high  # 1.0 at peak, lower = bigger drawdown
    drawdown = 1 - ratio
    if ratio < 0.60:
        score = 3.0
    elif ratio < 0.75:
        score = 2.0
    elif ratio < 0.90:
        score = 1.0
    else:
        score = 0.0
    return ([ScoreLine(
        "Drawdown > 25% from 52w high",
        score, 3.0,
        f"current={num(current)} vs 52w high={num(high)} (price={pct(ratio)} of high, drawdown={pct(drawdown)})",
    )], current, high, drawdown)


def _ncav(line_items: Iterable[LineItem],
          market_cap: float | None) -> tuple[list[ScoreLine], float | None]:
    items = list(line_items)
    ca_series = line_item_series(items, "current_assets")
    ta_series = line_item_series(items, "total_assets")
    te_series = line_item_series(items, "total_equity")
    if not (ca_series and ta_series and te_series):
        return ([ScoreLine("NCAV / mcap", 0.0, 3.0,
                           "balance-sheet inputs missing (CA / TA / TE)")], None)
    ca = ca_series[0].value
    ta = ta_series[0].value
    te = te_series[0].value
    if ca is None or ta is None or te is None:
        return ([ScoreLine("NCAV / mcap", 0.0, 3.0, "balance-sheet rows nan")], None)
    ncav = ca - (ta - te)
    if market_cap is None or market_cap == 0:
        return ([ScoreLine("NCAV / mcap", 0.0, 3.0,
                           f"NCAV={money(ncav)}; mcap n/a")], ncav)
    ratio = ncav / market_cap
    if ratio > 1.0:
        score = 3.0
    elif ratio > 0.5:
        score = 2.0
    elif ratio > 0.2:
        score = 1.0
    else:
        score = 0.0
    return ([ScoreLine(
        "NCAV / mcap > 0.2",
        score, 3.0,
        f"NCAV={money(ncav)} vs mcap={money(market_cap)} (ratio={pct(ratio)})",
    )], ncav)


def _pb(latest_fm: FinancialMetrics | None,
        line_items: Iterable[LineItem],
        market_cap: float | None) -> list[ScoreLine]:
    items = list(line_items)
    te_series = line_item_series(items, "total_equity")
    equity = te_series[0].value if te_series and te_series[0].value is not None else None
    if equity is None or market_cap in (None, 0):
        return [ScoreLine("Book yield equity/mcap > 0.5", 0.0, 2.0,
                           "equity or mcap n/a")]
    book_yield = equity / market_cap
    score = 2.0 if book_yield > 1.0 else (1.0 if book_yield > 0.5 else 0.0)
    return [ScoreLine(
        "Book yield equity/mcap > 0.5",
        score, 2.0,
        f"equity={money(equity)} / mcap={money(market_cap)} = {num(book_yield)} (P/B={num(1/book_yield) if book_yield else 'n/a'})",
    )]


def _contrarian_signal(drawdown_pct: float | None,
                        insider_trades: list[InsiderTrade]) -> list[ScoreLine]:
    if not insider_trades:
        return [ScoreLine("Contrarian insider buy", 0.0, 2.0, "no insider data")]
    buy = sum(t.shares or 0 for t in insider_trades if t.transaction_type == "buy")
    sell = sum(abs(t.shares or 0) for t in insider_trades
               if t.transaction_type in ("sell", "planned_sell"))
    net = buy - sell
    if net <= 0:
        return [ScoreLine("Contrarian insider buy", 0.0, 2.0,
                          f"net Δ={money(net)} (no insider buying)")]
    deep_drawdown = drawdown_pct is not None and drawdown_pct > 0.20
    score = 2.0 if deep_drawdown else 1.0
    detail = (
        f"net Δ={money(net)} (buying); "
        f"drawdown={pct(drawdown_pct)} "
        f"({'deep — full contrarian setup' if deep_drawdown else 'shallow — partial signal'})"
    )
    return [ScoreLine("Contrarian insider buy", score, 2.0, detail)]


def score(state) -> BurryScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    insider: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    prices: list[PriceBar] = state.get("shared_data:prices") or []
    market_cap = state.get("shared_data:market_cap")

    dd_lines, current, high, dd_pct = _drawdown(prices)
    ncav_lines, ncav_val = _ncav(line_items, market_cap)
    pb_lines = _pb(latest(metrics), line_items, market_cap)
    contrarian_lines = _contrarian_signal(dd_pct, insider)

    return BurryScore(
        drawdown=dd_lines,
        ncav=ncav_lines,
        pb=pb_lines,
        contrarian_signal=contrarian_lines,
        current_price=current,
        high_52w=high,
        drawdown_pct=dd_pct,
        ncav_value=ncav_val,
        market_cap=market_cap,
    )


def format_block(s: BurryScore) -> str:
    sections = [
        format_scorecard("Drawdown from 52w High", s.drawdown),
        format_scorecard("NCAV / Net-Net", s.ncav),
        format_scorecard("Book Yield (P/B inverse)", s.pb),
        format_scorecard("Contrarian Insider Buy", s.contrarian_signal),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  current_price: {num(s.current_price)}\n"
        f"  52w_high: {num(s.high_52w)}\n"
        f"  drawdown_pct: {pct(s.drawdown_pct)}\n"
        f"  ncav: {money(s.ncav_value)}\n"
        f"  market_cap: {money(s.market_cap)}"
    )
    return (
        "【Burry 量化 checklist — deep value + contrarian，找便宜得不可思議又有人偷偷在買的標的】\n"
        "scorecard 高分代表硬指標達標；Burry 真正的差異化在於「為什麼市場是錯的」的結構性論點，那部分必須從分析師報告與你的研究中補。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
