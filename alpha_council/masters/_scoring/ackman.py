"""Bill Ackman — concentrated activism, catalyst-driven value unlock.

Ackman's edge is buying high-quality businesses whose operating or capital-
allocation slack creates a wedge between current price and what an
activist can extract via buybacks, spin-offs, or management change. The
scoring tries to surface that wedge: real underlying quality + observable
underperformance + concrete activist levers.

  Underlying quality (3)   ROE > 12% (2) | Gross margin > 30% (1)
  Margin compression (3)   Current op margin vs 5y peak: gap > 30% (3)
                           > 15% (2) | > 5% (1) — gap means activist room
  Capital allocation room  Cash hoarding (mcap-relative) (1) +
    (2)                    Low payout / no buybacks (1)
  Catalyst proximity (2)   Recent MOPS 重大訊息 mentions
                           restructuring / M&A keywords (1) +
                           Insider net selling (1) — leadership churn risk

Total cap 10. We can't score "activist filing" directly because there's no
free 13D feed; the LLM persona supplies that read from the news_report.
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
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
)


_CATALYST_KEYWORDS = (
    "分割", "分拆", "spin", "split",
    "併購", "合併", "收購", "merger", "acquisition", "acquire",
    "重組", "restructur", "reorganiz",
    "出售", "處分", "divest",
    "私有化", "下市", "buyout",
    "資產重評", "減資", "增資",
    "公司治理", "改選董事",
)


@dataclass(frozen=True)
class AckmanScore:
    quality: list[ScoreLine] = field(default_factory=list)
    margin_compression: list[ScoreLine] = field(default_factory=list)
    capital_allocation_room: list[ScoreLine] = field(default_factory=list)
    catalyst_proximity: list[ScoreLine] = field(default_factory=list)
    op_margin_now: float | None = None
    op_margin_peak: float | None = None
    market_cap: float | None = None

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.quality,
            self.margin_compression,
            self.capital_allocation_room,
            self.catalyst_proximity,
        )


def _quality(latest_fm: FinancialMetrics | None) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("Underlying quality", 0.0, 3.0, "no metrics")]
    roe = latest_fm.return_on_equity
    gm = latest_fm.gross_margin
    lines = [
        ScoreLine(
            "ROE > 12%",
            2.0 if (roe is not None and roe > 0.12) else 0.0,
            2.0,
            f"ROE={pct(roe)}" if roe is not None else "ROE n/a",
        ),
        ScoreLine(
            "Gross margin > 30%",
            1.0 if (gm is not None and gm > 0.30) else 0.0,
            1.0,
            f"gross_margin={pct(gm)}" if gm is not None else "gross margin n/a",
        ),
    ]
    return lines


def _margin_compression(metrics: list[FinancialMetrics]) -> tuple[list[ScoreLine], float | None, float | None]:
    margins = [(f.period_end, f.operating_margin) for f in metrics if f.operating_margin is not None]
    if len(margins) < 2:
        return ([ScoreLine("Op margin gap vs peak", 0.0, 3.0,
                            f"need ≥2 op-margin points; have {len(margins)}")], None, None)
    margins.sort(key=lambda t: t[0])
    now = margins[-1][1]
    peak = max(m for _, m in margins)
    if peak <= 0:
        return ([ScoreLine("Op margin gap vs peak", 0.0, 3.0,
                            f"peak op_margin={pct(peak)} (non-positive)")], now, peak)
    gap = (peak - now) / peak
    if gap > 0.30:
        score = 3.0
    elif gap > 0.15:
        score = 2.0
    elif gap > 0.05:
        score = 1.0
    else:
        score = 0.0
    return ([ScoreLine(
        "Op margin gap vs peak",
        score, 3.0,
        f"now={pct(now)} vs peak={pct(peak)} → gap={pct(gap)}",
    )], now, peak)


def _capital_allocation_room(latest_fm: FinancialMetrics | None,
                              line_items: Iterable[LineItem],
                              market_cap: float | None) -> list[ScoreLine]:
    items = list(line_items)
    cash_series = line_item_series(items, "cash_and_equivalents")
    cash = cash_series[0].value if cash_series and cash_series[0].value is not None else None
    lines: list[ScoreLine] = []
    if cash is not None and market_cap and market_cap > 0:
        cash_ratio = cash / market_cap
        lines.append(ScoreLine(
            "Cash hoarding (cash/mcap > 10%)",
            1.0 if cash_ratio > 0.10 else 0.0,
            1.0,
            f"cash/mcap={pct(cash_ratio)} (cash={money(cash)})",
        ))
    else:
        lines.append(ScoreLine("Cash hoarding", 0.0, 1.0, "cash or mcap n/a"))

    div_series = line_item_series(items, "dividends_paid")
    div = div_series[0].value if div_series and div_series[0].value is not None else None
    ni = latest_fm.net_income if latest_fm else None
    shares = list(line_item_series(items, "shares_outstanding"))
    payout_low = False
    if div is not None and ni and ni > 0:
        payout = abs(div) / ni
        payout_low = payout < 0.20
    buyback_absent = False
    if len(shares) >= 2 and shares[0].value is not None and shares[-1].value is not None:
        buyback_absent = shares[0].value >= shares[-1].value
    if payout_low or buyback_absent:
        detail_parts = []
        if payout_low:
            detail_parts.append(f"low payout {pct(payout) if ni else 'n/a'}")
        if buyback_absent:
            detail_parts.append("no buyback")
        lines.append(ScoreLine(
            "Capital return room (low payout / no buyback)",
            1.0, 1.0,
            "; ".join(detail_parts),
        ))
    else:
        lines.append(ScoreLine(
            "Capital return room (low payout / no buyback)",
            0.0, 1.0,
            "already returning capital meaningfully",
        ))
    return lines


def _catalyst_proximity(news: list[CompanyNews],
                         insider_trades: list[InsiderTrade]) -> list[ScoreLine]:
    matched = []
    for n in news:
        haystack = " ".join(filter(None, [n.title, n.summary])).lower()
        for kw in _CATALYST_KEYWORDS:
            if kw.lower() in haystack:
                matched.append((kw, n.title))
                break
    lines: list[ScoreLine] = []
    if matched:
        snippets = "; ".join(f"[{kw}] {title[:30]}" for kw, title in matched[:3])
        lines.append(ScoreLine(
            "Catalyst keyword in recent filings",
            1.0, 1.0,
            f"{len(matched)} match(es): {snippets}",
        ))
    else:
        lines.append(ScoreLine(
            "Catalyst keyword in recent filings",
            0.0, 1.0,
            f"0 matches across {len(news)} news items",
        ))

    if not insider_trades:
        lines.append(ScoreLine("Insider net selling", 0.0, 1.0, "no insider data"))
    else:
        buy = sum(t.shares or 0 for t in insider_trades if t.transaction_type == "buy")
        sell = sum(abs(t.shares or 0) for t in insider_trades
                   if t.transaction_type in ("sell", "planned_sell"))
        net = buy - sell
        # Ackman's logic is *reverse* of Buffett's: insider selling = potential
        # leadership change opportunity for an activist.
        score = 1.0 if net < 0 else 0.0
        lines.append(ScoreLine(
            "Insider net selling (activist signal)",
            score, 1.0,
            f"net Δ={money(net)} ({'selling — possible churn' if net < 0 else 'buying/flat'})",
        ))
    return lines


def score(state) -> AckmanScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    insider: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    news: list[CompanyNews] = state.get("shared_data:company_news") or []
    market_cap = state.get("shared_data:market_cap")
    latest_fm = latest(metrics)
    margin_lines, now, peak = _margin_compression(metrics)
    return AckmanScore(
        quality=_quality(latest_fm),
        margin_compression=margin_lines,
        capital_allocation_room=_capital_allocation_room(latest_fm, line_items, market_cap),
        catalyst_proximity=_catalyst_proximity(news, insider),
        op_margin_now=now,
        op_margin_peak=peak,
        market_cap=market_cap,
    )


def format_block(s: AckmanScore) -> str:
    sections = [
        format_scorecard("Underlying Quality", s.quality),
        format_scorecard("Margin Compression (room for activism)", s.margin_compression),
        format_scorecard("Capital Allocation Room", s.capital_allocation_room),
        format_scorecard("Catalyst Proximity", s.catalyst_proximity),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  op_margin_now: {pct(s.op_margin_now)}\n"
        f"  op_margin_peak: {pct(s.op_margin_peak)}\n"
        f"  market_cap: {money(s.market_cap)}"
    )
    return (
        "【Ackman 量化 checklist — concentrated activism，找品質好但被低估/錯置資本的標的】\n"
        "scorecard 高分 ≠ 自動買進，需配合分析師報告判斷活躍主義是否實際可行（13D 申報、董事會結構、股權集中度）。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
