"""Peter Lynch — growth at a reasonable price, simple stories, ten-bagger hunt.

Lynch liked businesses an ordinary investor could explain in one sentence,
growing fast enough to matter but not so expensive that all upside was already
priced in. Public data cannot reproduce his field research, so the scorecard
leans on observable proxies and leaves the final story test to the LLM.

  Growth profile (3)       Revenue CAGR > 10% (1) + earnings CAGR > 10% (1) +
                           positive latest earnings (1)
  PEG sanity (2)           PEG < 1.0 (2) | < 2.0 (1)
  Financial practicality   Debt/equity < 1.0 (1) + current ratio > 1.2 (1)
    (2)
  Ten-bagger proxies (3)   Revenue CAGR > 15% (1) + no dilution (1) +
                           expansion/news support (1)

Total cap 10. The stock-type classification is heuristic and is meant to help
the persona answer in Lynch's own buckets rather than as a hard signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from alpha_council.masters._scoring.common import (
    ScoreLine,
    compute_cagr,
    format_scorecard,
    latest,
    line_item_series,
    money,
    num,
    pct,
)
from alpha_council.providers.base import CompanyNews, FinancialMetrics, LineItem

_EXPANSION_KEYWORDS = (
    "expand",
    "expansion",
    "store",
    "opening",
    "launch",
    "rollout",
    "subscriber",
    "adoption",
    "market share",
    "new product",
    "新店",
    "展店",
    "擴張",
    "擴產",
    "新品",
    "成長",
)


@dataclass(frozen=True)
class LynchScore:
    growth_profile: list[ScoreLine] = field(default_factory=list)
    peg_sanity: list[ScoreLine] = field(default_factory=list)
    financial_practicality: list[ScoreLine] = field(default_factory=list)
    ten_bagger_proxies: list[ScoreLine] = field(default_factory=list)
    revenue_cagr: float | None = None
    earnings_cagr: float | None = None
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    stock_type: str = "unclassified"
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
            self.growth_profile,
            self.peg_sanity,
            self.financial_practicality,
            self.ten_bagger_proxies,
        )


def _growth_profile(
    metrics: list[FinancialMetrics],
) -> tuple[list[ScoreLine], float | None, float | None]:
    rev_points = [(f.period_end, f.revenue) for f in metrics if f.revenue and f.revenue > 0]
    ni_points = [(f.period_end, f.net_income) for f in metrics if f.net_income and f.net_income > 0]
    rev_cagr, _, _, rev_desc = compute_cagr(rev_points, cap=0.50)
    ni_cagr, _, _, ni_desc = compute_cagr(ni_points, cap=0.50)
    latest_fm = latest(metrics)

    lines: list[ScoreLine] = []
    lines.append(
        ScoreLine(
            "Revenue CAGR > 10%",
            1.0 if rev_cagr is not None and rev_cagr > 0.10 else 0.0,
            1.0,
            f"revenue CAGR={pct(rev_cagr)} ({rev_desc})" if rev_cagr is not None else f"unavailable ({rev_desc})",
        )
    )
    lines.append(
        ScoreLine(
            "Earnings CAGR > 10%",
            1.0 if ni_cagr is not None and ni_cagr > 0.10 else 0.0,
            1.0,
            f"earnings CAGR={pct(ni_cagr)} ({ni_desc})" if ni_cagr is not None else f"unavailable ({ni_desc})",
        )
    )
    ni = latest_fm.net_income if latest_fm else None
    lines.append(
        ScoreLine(
            "Latest earnings positive",
            1.0 if ni is not None and ni > 0 else 0.0,
            1.0,
            f"latest net_income={money(ni)}" if ni is not None else "latest net_income n/a",
        )
    )
    return lines, rev_cagr, ni_cagr


def _peg_sanity(
    latest_fm: FinancialMetrics | None,
    earnings_cagr: float | None,
    market_cap: float | None,
) -> tuple[list[ScoreLine], float | None, float | None]:
    if latest_fm is None or latest_fm.net_income in (None, 0) or market_cap in (None, 0):
        return [ScoreLine("PEG < 1.0", 0.0, 2.0, "P/E inputs n/a")], None, None
    pe = market_cap / latest_fm.net_income
    if pe <= 0 or earnings_cagr is None or earnings_cagr <= 0:
        return [
            ScoreLine(
                "PEG < 1.0",
                0.0,
                2.0,
                f"P/E={num(pe)}, growth={pct(earnings_cagr)} (PEG undefined)",
            )
        ], pe, None
    peg = pe / (earnings_cagr * 100)
    score = 2.0 if peg < 1.0 else (1.0 if peg < 2.0 else 0.0)
    return [
        ScoreLine(
            "PEG < 1.0",
            score,
            2.0,
            f"P/E={num(pe)} / earnings growth={pct(earnings_cagr)} -> PEG={num(peg)}",
        )
    ], pe, peg


def _financial_practicality(
    latest_fm: FinancialMetrics | None,
) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("Financial practicality", 0.0, 2.0, "no metrics")]
    dte = latest_fm.debt_to_equity
    current_ratio = latest_fm.current_ratio
    return [
        ScoreLine(
            "Debt/equity < 1.0",
            1.0 if dte is not None and dte < 1.0 else 0.0,
            1.0,
            f"debt_to_equity={num(dte)}" if dte is not None else "debt_to_equity n/a",
        ),
        ScoreLine(
            "Current ratio > 1.2",
            1.0 if current_ratio is not None and current_ratio > 1.2 else 0.0,
            1.0,
            f"current_ratio={num(current_ratio)}" if current_ratio is not None else "current_ratio n/a",
        ),
    ]


def _ten_bagger_proxies(
    rev_cagr: float | None,
    line_items: list[LineItem],
    news: list[CompanyNews],
) -> list[ScoreLine]:
    lines: list[ScoreLine] = []
    lines.append(
        ScoreLine(
            "Revenue CAGR > 15%",
            1.0 if rev_cagr is not None and rev_cagr > 0.15 else 0.0,
            1.0,
            f"revenue CAGR={pct(rev_cagr)}" if rev_cagr is not None else "revenue CAGR n/a",
        )
    )

    shares = line_item_series(line_items, "shares_outstanding")
    if len(shares) >= 2 and shares[0].value not in (None, 0) and shares[-1].value is not None:
        dilution = (shares[0].value - shares[-1].value) / shares[-1].value
        score = 1.0 if dilution <= 0.05 else 0.0
        detail = f"shares change={pct(dilution)} over observed history"
    else:
        score = 0.0
        detail = "shares history insufficient"
    lines.append(ScoreLine("No material dilution", score, 1.0, detail))

    matched_titles = []
    for item in news:
        haystack = " ".join(filter(None, [item.title, item.summary])).lower()
        if any(kw.lower() in haystack for kw in _EXPANSION_KEYWORDS):
            matched_titles.append(item.title)
    lines.append(
        ScoreLine(
            "Expansion / adoption narrative support",
            1.0 if matched_titles else 0.0,
            1.0,
            f"{len(matched_titles)} supportive news item(s)" if matched_titles else f"0 matches across {len(news)} news items",
        )
    )
    return lines


def _classify_stock(
    revenue_cagr: float | None,
    latest_fm: FinancialMetrics | None,
    market_cap: float | None,
    line_items: list[LineItem],
) -> str:
    if latest_fm is None:
        return "unclassified"
    if latest_fm.net_income is not None and latest_fm.net_income <= 0 and revenue_cagr and revenue_cagr > 0.08:
        return "turnaround"

    equity_series = line_item_series(line_items, "total_equity")
    equity = equity_series[0].value if equity_series and equity_series[0].value is not None else None
    if equity is not None and market_cap not in (None, 0) and equity / market_cap > 0.9:
        return "asset_play"

    if revenue_cagr is None:
        return "stalwart_or_cyclical"
    if revenue_cagr >= 0.20:
        return "fast_grower"
    if revenue_cagr >= 0.10:
        return "stalwart"
    if revenue_cagr > 0.02:
        return "slow_grower"
    return "cyclical_or_stalled"


def score(state) -> LynchScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    news: list[CompanyNews] = state.get("shared_data:company_news") or []
    market_cap = state.get("shared_data:market_cap")
    sorted_metrics = sorted(metrics, key=lambda f: f.period_end) if metrics else []
    latest_fm = latest(metrics)

    growth_lines, rev_cagr, ni_cagr = _growth_profile(sorted_metrics)
    peg_lines, pe, peg = _peg_sanity(latest_fm, ni_cagr, market_cap)

    return LynchScore(
        growth_profile=growth_lines,
        peg_sanity=peg_lines,
        financial_practicality=_financial_practicality(latest_fm),
        ten_bagger_proxies=_ten_bagger_proxies(rev_cagr, line_items, news),
        revenue_cagr=rev_cagr,
        earnings_cagr=ni_cagr,
        pe_ratio=pe,
        peg_ratio=peg,
        stock_type=_classify_stock(rev_cagr, latest_fm, market_cap, line_items),
        market_cap=market_cap,
    )


def format_block(s: LynchScore) -> str:
    sections = [
        format_scorecard("Growth Profile", s.growth_profile),
        format_scorecard("PEG Sanity", s.peg_sanity),
        format_scorecard("Financial Practicality", s.financial_practicality),
        format_scorecard("Ten-Bagger Proxies", s.ten_bagger_proxies),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  stock_type: {s.stock_type}\n"
        f"  revenue_cagr: {pct(s.revenue_cagr)}\n"
        f"  earnings_cagr: {pct(s.earnings_cagr)}\n"
        f"  pe_ratio: {num(s.pe_ratio)}\n"
        f"  peg_ratio: {num(s.peg_ratio)}\n"
        f"  market_cap: {money(s.market_cap)}"
    )
    return (
        "【Lynch 量化 checklist — GARP + practical growth + ten-bagger hunt】\n"
        "高分代表成長、價格、資產負債表與擴張 proxy 大致對得上；Lynch 真正的優勢仍在於『這是不是你看得懂、願意長期追蹤的故事』。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
