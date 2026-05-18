"""Aswath Damodaran — story-to-numbers, DCF, relative valuation.

Damodaran's signature exercise is forcing a business narrative through to
explicit numbers and discounting. The scoring runs that exercise with the
inputs yfinance / TWSE actually expose, so the LLM persona has to argue
against (or with) a real DCF rather than hand-waving.

  DCF intrinsic (4)         5-year explicit OE growth + Gordon terminal,
                            10% discount, 3% terminal growth
                            intrinsic/mcap > 1.5 (4) | > 1.0 (2) | > 0.7 (1)
  Reinvestment quality (2)  CapEx/Rev in [5%, 50%] (1) + implied growth
                            roughly matches reinvestment plausibility (1)
  Multiple sanity (2)       P/E in [10, 25] (2) | (25, 35] (1)
                            else 0 (too cheap likely value trap or
                            too rich without growth to support it)
  Cost-of-capital cover (2) Earnings yield > 10% (2) | > 8% (1)

Total cap 10. Discount rate fixed at 10% because we don't pull beta /
ERP; the LLM persona is expected to flex this when the analyst report
indicates higher/lower-risk industry context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from alpha_council.masters._scoring.common import (
    ScoreLine,
    compute_cagr,
    compute_owner_earnings,
    format_scorecard,
    latest,
    line_item_series,
    money,
    num,
    pct,
)
from alpha_council.providers.base import FinancialMetrics, LineItem

_DISCOUNT_RATE = 0.10
_TERMINAL_GROWTH = 0.03
_PROJECTION_YEARS = 5


@dataclass(frozen=True)
class DamodaranScore:
    dcf: list[ScoreLine] = field(default_factory=list)
    reinvestment: list[ScoreLine] = field(default_factory=list)
    multiple_sanity: list[ScoreLine] = field(default_factory=list)
    cost_of_capital: list[ScoreLine] = field(default_factory=list)
    dcf_intrinsic: float | None = None
    market_cap: float | None = None
    dcf_ratio: float | None = None
    revenue_cagr: float | None = None
    pe_ratio: float | None = None
    earnings_yield: float | None = None

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (self.dcf, self.reinvestment, self.multiple_sanity, self.cost_of_capital)


def _dcf(
    metrics: list[FinancialMetrics],
    line_items: Iterable[LineItem],
    latest_fm: FinancialMetrics | None,
    market_cap: float | None,
) -> tuple[list[ScoreLine], float | None, float | None, float | None]:
    owner_earnings, oe_derivation = compute_owner_earnings(latest_fm, line_items)
    if owner_earnings is None or market_cap is None or market_cap == 0:
        return ([ScoreLine("DCF intrinsic / mcap", 0.0, 4.0,
                           f"{oe_derivation}; market_cap={money(market_cap)}")],
                None, None, None)

    rev_points = [
        (f.period_end, f.revenue)
        for f in metrics
        if f.revenue is not None and f.revenue > 0
    ]
    cagr, capped, years, cagr_desc = compute_cagr(rev_points, cap=0.20, floor=-0.05)
    growth = capped if capped is not None else 0.03

    # 5-year explicit projection of OE at observed (capped) growth, then
    # Gordon terminal value at 3%.
    pv = 0.0
    for t in range(1, _PROJECTION_YEARS + 1):
        oe_t = owner_earnings * (1 + growth) ** t
        pv += oe_t / (1 + _DISCOUNT_RATE) ** t
    terminal_oe = owner_earnings * (1 + growth) ** _PROJECTION_YEARS * (1 + _TERMINAL_GROWTH)
    terminal_value = terminal_oe / (_DISCOUNT_RATE - _TERMINAL_GROWTH)
    pv += terminal_value / (1 + _DISCOUNT_RATE) ** _PROJECTION_YEARS

    ratio = pv / market_cap
    if ratio > 1.5:
        score = 4.0
    elif ratio > 1.0:
        score = 2.0
    elif ratio > 0.7:
        score = 1.0
    else:
        score = 0.0
    detail = (
        f"OE base={money(owner_earnings)} ({oe_derivation}); "
        f"growth={pct(growth)} (raw {pct(cagr)} from {cagr_desc}); "
        f"DCF intrinsic≈{money(pv)}; intrinsic/mcap={num(ratio)}×"
    )
    return [ScoreLine("DCF intrinsic / mcap > 1.0", score, 4.0, detail)], pv, ratio, cagr


def _reinvestment(latest_fm: FinancialMetrics | None,
                   line_items: Iterable[LineItem]) -> list[ScoreLine]:
    if latest_fm is None or latest_fm.revenue in (None, 0):
        return [ScoreLine("Reinvestment quality", 0.0, 2.0, "no metrics")]
    capex_series = line_item_series(list(line_items), "capital_expenditure")
    capex = capex_series[0].value if capex_series and capex_series[0].value is not None else None
    lines: list[ScoreLine] = []
    if capex is None:
        lines.append(ScoreLine("CapEx/Rev in [5%, 50%]", 0.0, 1.0, "capex n/a"))
        intensity = None
    else:
        intensity = abs(capex) / latest_fm.revenue
        in_band = 0.05 <= intensity <= 0.50
        lines.append(ScoreLine(
            "CapEx/Rev in [5%, 50%]",
            1.0 if in_band else 0.0,
            1.0,
            f"CapEx/Rev={pct(intensity)} "
            f"({'in band' if in_band else 'starved' if intensity < 0.05 else 'over-investing'})",
        ))

    # Implied reinvestment rate = growth / ROIC.  If ROIC is healthy and the
    # implied rate matches observed CapEx/Rev within an order of magnitude,
    # the growth story is self-funded — Damodaran's key consistency check.
    roic = latest_fm.return_on_invested_capital or latest_fm.return_on_equity
    g_rev = latest_fm.revenue_growth_yoy
    if roic is not None and roic > 0 and g_rev is not None and intensity is not None:
        implied = g_rev / roic
        plausible = 0.1 * intensity <= implied <= 10 * intensity if intensity > 0 else False
        lines.append(ScoreLine(
            "Growth-funding plausible",
            1.0 if plausible else 0.0,
            1.0,
            f"implied reinv rate={pct(implied)} (g={pct(g_rev)}/roic={pct(roic)}); "
            f"observed CapEx/Rev={pct(intensity)}",
        ))
    else:
        lines.append(ScoreLine("Growth-funding plausible", 0.0, 1.0,
                                "need ROIC>0 + revenue growth + capex"))
    return lines


def _multiple_sanity(latest_fm: FinancialMetrics | None,
                      market_cap: float | None) -> tuple[list[ScoreLine], float | None]:
    if latest_fm is None or latest_fm.net_income in (None, 0) or market_cap in (None, 0):
        return ([ScoreLine("P/E in [10, 25]", 0.0, 2.0, "P/E inputs n/a")], None)
    pe = market_cap / latest_fm.net_income
    if pe <= 0:
        return ([ScoreLine("P/E in [10, 25]", 0.0, 2.0, f"P/E={num(pe)} (negative earnings)")], pe)
    if 10 <= pe <= 25:
        score, verdict = 2.0, "in healthy band"
    elif 25 < pe <= 35:
        score, verdict = 1.0, "elevated — growth must support it"
    elif pe < 10:
        score, verdict = 0.0, "very cheap — possible value trap or earnings risk"
    else:
        score, verdict = 0.0, "expensive — needs explicit story"
    return ([ScoreLine("P/E in [10, 25]", score, 2.0, f"P/E={num(pe)} ({verdict})")], pe)


def _cost_of_capital(latest_fm: FinancialMetrics | None,
                      market_cap: float | None) -> tuple[list[ScoreLine], float | None]:
    if latest_fm is None or latest_fm.net_income in (None, 0) or market_cap in (None, 0):
        return ([ScoreLine("Earnings yield > 10%", 0.0, 2.0, "inputs n/a")], None)
    ey = latest_fm.net_income / market_cap
    score = 2.0 if ey > 0.10 else (1.0 if ey > 0.08 else 0.0)
    return ([ScoreLine("Earnings yield > 10%", score, 2.0,
                       f"E/P={pct(ey)} vs discount rate {pct(_DISCOUNT_RATE)}")], ey)


def score(state) -> DamodaranScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    market_cap = state.get("shared_data:market_cap")
    latest_fm = latest(metrics)
    sorted_metrics = sorted(metrics, key=lambda f: f.period_end) if metrics else []

    dcf_lines, intrinsic, dcf_ratio, rev_cagr = _dcf(sorted_metrics, line_items, latest_fm, market_cap)
    mult_lines, pe = _multiple_sanity(latest_fm, market_cap)
    coc_lines, ey = _cost_of_capital(latest_fm, market_cap)

    return DamodaranScore(
        dcf=dcf_lines,
        reinvestment=_reinvestment(latest_fm, line_items),
        multiple_sanity=mult_lines,
        cost_of_capital=coc_lines,
        dcf_intrinsic=intrinsic,
        market_cap=market_cap,
        dcf_ratio=dcf_ratio,
        revenue_cagr=rev_cagr,
        pe_ratio=pe,
        earnings_yield=ey,
    )


def format_block(s: DamodaranScore) -> str:
    sections = [
        format_scorecard("DCF Intrinsic (5y + terminal)", s.dcf),
        format_scorecard("Reinvestment Quality", s.reinvestment),
        format_scorecard("Multiple Sanity (P/E)", s.multiple_sanity),
        format_scorecard("Cost-of-Capital Coverage (E/P)", s.cost_of_capital),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  dcf_intrinsic: {money(s.dcf_intrinsic)}\n"
        f"  market_cap: {money(s.market_cap)}\n"
        f"  intrinsic/mcap: {num(s.dcf_ratio)}\n"
        f"  pe_ratio: {num(s.pe_ratio)}\n"
        f"  earnings_yield: {pct(s.earnings_yield)}\n"
        f"  revenue_cagr (observed): {pct(s.revenue_cagr)}\n"
        f"  discount_rate (fixed): {pct(_DISCOUNT_RATE)}\n"
        f"  terminal_growth (fixed): {pct(_TERMINAL_GROWTH)}"
    )
    return (
        "【Damodaran 量化 checklist — story-to-numbers，DCF + 相對估值 + 風險折現】\n"
        f"DCF 假設：5 年顯式成長（用觀察到的 revenue CAGR，封頂 20%、下限 -5%）+ 終值 (g={pct(_TERMINAL_GROWTH)})，折現 {pct(_DISCOUNT_RATE)}。\n"
        "如果分析師報告指出產業 beta 偏離一般，請在敘事中明示要把折現率往哪個方向調，scorecard 用固定 10%。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
