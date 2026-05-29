"""Rakesh Jhunjhunwala — quality growth at a reasonable price, high
conviction, long holds.

Jhunjhunwala (the "Big Bull" of Indian markets) sat between Buffett's
quality bias and Lynch's growth appetite: he wanted compounding revenue
plus operating leverage, sustained ROE, and a price that didn't require
heroic growth assumptions. He concentrated heavily in his best ideas, so
the scoring also rewards low operational volatility — concentration is
only sane when the business is steady.

  Quality growth (3)        Revenue CAGR > 10% (1) +
                            earnings growth > revenue growth (operating
                            leverage) (2)
  ROE persistence (3)       ROE > 15% in all observed years (3) |
                            ≥ 60% of years (1)
  Reasonable PEG (2)        PEG (P/E divided by growth) < 1.5 (2) |
                            < 2.5 (1)
  Concentration worthy (2)  Earnings positive every observed year (1) +
                            Operating margin σ < 4pp (1)

Total cap 10. "Long-term holding worthiness" is the lens the LLM should
use when interpreting these numbers — would Jhunjhunwala have been happy
to sit on this for a decade?
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev

from alpha_council.masters._scoring.common import (
    ScoreLine,
    compute_cagr,
    format_scorecard,
    latest,
    money,
    num,
    pct,
)
from alpha_council.providers.base import FinancialMetrics


@dataclass(frozen=True)
class JhunjhunwalaScore:
    quality_growth: list[ScoreLine] = field(default_factory=list)
    roe_persistence: list[ScoreLine] = field(default_factory=list)
    reasonable_peg: list[ScoreLine] = field(default_factory=list)
    concentration_worthy: list[ScoreLine] = field(default_factory=list)
    revenue_cagr: float | None = None
    earnings_cagr: float | None = None
    pe_ratio: float | None = None
    peg_ratio: float | None = None
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
            self.quality_growth,
            self.roe_persistence,
            self.reasonable_peg,
            self.concentration_worthy,
        )


def _quality_growth(metrics: list[FinancialMetrics]) -> tuple[list[ScoreLine], float | None, float | None]:
    rev_points = [(f.period_end, f.revenue) for f in metrics
                  if f.revenue is not None and f.revenue > 0]
    ni_points = [(f.period_end, f.net_income) for f in metrics
                 if f.net_income is not None and f.net_income > 0]
    rev_cagr, _, _, rev_desc = compute_cagr(rev_points, cap=0.50)
    ni_cagr, _, _, ni_desc = compute_cagr(ni_points, cap=0.50)

    lines: list[ScoreLine] = []
    if rev_cagr is None:
        lines.append(ScoreLine("Revenue CAGR > 10%", 0.0, 1.0, f"unavailable ({rev_desc})"))
    else:
        lines.append(ScoreLine(
            "Revenue CAGR > 10%",
            1.0 if rev_cagr > 0.10 else 0.0,
            1.0,
            f"revenue CAGR={pct(rev_cagr)} ({rev_desc})",
        ))

    if rev_cagr is None or ni_cagr is None:
        lines.append(ScoreLine("Earnings growth > Revenue growth (op leverage)",
                                0.0, 2.0,
                                "need both revenue and earnings CAGR"))
    else:
        leverage = ni_cagr - rev_cagr
        if leverage > 0.03:
            score, verdict = 2.0, "clear operating leverage"
        elif leverage > 0:
            score, verdict = 1.0, "weak operating leverage"
        else:
            score, verdict = 0.0, "earnings lagging revenue"
        lines.append(ScoreLine(
            "Earnings growth > Revenue growth (op leverage)",
            score, 2.0,
            f"earnings CAGR={pct(ni_cagr)} vs revenue CAGR={pct(rev_cagr)} → leverage={pct(leverage)} ({verdict})",
        ))
    return lines, rev_cagr, ni_cagr


def _roe_persistence(metrics: list[FinancialMetrics]) -> list[ScoreLine]:
    roes = [f.return_on_equity for f in metrics if f.return_on_equity is not None]
    if not roes:
        return [ScoreLine("ROE > 15% sustained", 0.0, 3.0, "no ROE history")]
    n = len(roes)
    qualifying = sum(1 for r in roes if r > 0.15)
    if qualifying == n:
        score, verdict = 3.0, f"all {n} observed years"
    elif qualifying >= n * 0.6:
        score, verdict = 1.0, f"{qualifying}/{n} years"
    else:
        score, verdict = 0.0, f"only {qualifying}/{n} years"
    return [ScoreLine("ROE > 15% sustained", score, 3.0,
                       f"{verdict}; latest ROE={pct(roes[0])}")]


def _reasonable_peg(latest_fm: FinancialMetrics | None,
                     ni_cagr: float | None,
                     market_cap: float | None) -> tuple[list[ScoreLine], float | None, float | None]:
    if latest_fm is None or latest_fm.net_income in (None, 0) or market_cap in (None, 0):
        return ([ScoreLine("PEG < 1.5", 0.0, 2.0, "P/E inputs n/a")], None, None)
    pe = market_cap / latest_fm.net_income
    if pe <= 0 or ni_cagr is None or ni_cagr <= 0:
        return ([ScoreLine("PEG < 1.5", 0.0, 2.0,
                            f"P/E={num(pe)}, growth={pct(ni_cagr)} (PEG undefined)")], pe, None)
    peg = pe / (ni_cagr * 100)
    if peg < 1.5:
        score = 2.0
    elif peg < 2.5:
        score = 1.0
    else:
        score = 0.0
    return ([ScoreLine("PEG < 1.5", score, 2.0,
                        f"P/E={num(pe)} / growth={pct(ni_cagr)} → PEG={num(peg)}")],
            pe, peg)


def _concentration_worthy(metrics: list[FinancialMetrics]) -> list[ScoreLine]:
    nis = [f.net_income for f in metrics if f.net_income is not None]
    op_margins = [f.operating_margin for f in metrics if f.operating_margin is not None]

    lines: list[ScoreLine] = []
    if not nis:
        lines.append(ScoreLine("Earnings positive every year", 0.0, 1.0, "no NI history"))
    else:
        all_positive = all(v > 0 for v in nis)
        lines.append(ScoreLine(
            "Earnings positive every year",
            1.0 if all_positive else 0.0,
            1.0,
            f"{sum(1 for v in nis if v > 0)}/{len(nis)} positive",
        ))

    if len(op_margins) < 3:
        lines.append(ScoreLine("Op margin σ < 4pp", 0.0, 1.0,
                                f"<3 op-margin points ({len(op_margins)} available)"))
    else:
        sd = pstdev(op_margins)
        lines.append(ScoreLine(
            "Op margin σ < 4pp",
            1.0 if sd < 0.04 else 0.0,
            1.0,
            f"σ(op_margin)={pct(sd)} over {len(op_margins)} years",
        ))
    return lines


def score(state) -> JhunjhunwalaScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    market_cap = state.get("shared_data:market_cap")
    sorted_metrics = sorted(metrics, key=lambda f: f.period_end) if metrics else []
    latest_fm = latest(metrics)

    qg_lines, rev_cagr, ni_cagr = _quality_growth(sorted_metrics)
    peg_lines, pe, peg = _reasonable_peg(latest_fm, ni_cagr, market_cap)

    return JhunjhunwalaScore(
        quality_growth=qg_lines,
        roe_persistence=_roe_persistence(metrics),
        reasonable_peg=peg_lines,
        concentration_worthy=_concentration_worthy(metrics),
        revenue_cagr=rev_cagr,
        earnings_cagr=ni_cagr,
        pe_ratio=pe,
        peg_ratio=peg,
        market_cap=market_cap,
    )


def format_block(s: JhunjhunwalaScore) -> str:
    sections = [
        format_scorecard("Quality Growth", s.quality_growth),
        format_scorecard("ROE Persistence", s.roe_persistence),
        format_scorecard("Reasonable PEG", s.reasonable_peg),
        format_scorecard("Concentration-worthy Stability", s.concentration_worthy),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  revenue_cagr: {pct(s.revenue_cagr)}\n"
        f"  earnings_cagr: {pct(s.earnings_cagr)}\n"
        f"  pe_ratio: {num(s.pe_ratio)}\n"
        f"  peg_ratio: {num(s.peg_ratio)}\n"
        f"  market_cap: {money(s.market_cap)}"
    )
    return (
        "【Jhunjhunwala 量化 checklist — quality growth + reasonable price + high conviction】\n"
        "高分代表「值得集中、長期持有」的硬指標到位；最終是否符合 Jhunjhunwala 風格，仍要看你對產業與管理層的判斷。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
