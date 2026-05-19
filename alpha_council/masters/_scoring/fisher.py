"""Phil Fisher — durable growth, management execution, scuttlebutt proxies.

Fisher's real edge came from scuttlebutt: talking to customers, suppliers,
competitors, and former employees. We do not have that data feed, so the
deterministic scorecard uses public-market proxies for the same ideas.

  Long-term growth quality (3)   Revenue CAGR > 10% (1) + gross margin > 35%
                                 or op margin > 12% (1) + positive earnings
                                 in most observed years (1)
  R&D commitment (2)             R&D/revenue > 5% (1) + recurring R&D history
                                 or innovation-news support (1)
  Management execution (3)       Op margin stable/improving (1) + ROE > 12%
                                 (1) + no material dilution (1)
  Scuttlebutt/news support (2)   Product/customer/adoption keywords (1) +
                                 insider alignment (1)

Total cap 10. Missing R&D or insider data should be treated as unverified, not
as evidence against the company.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev

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
from alpha_council.providers.base import CompanyNews, FinancialMetrics, InsiderTrade, LineItem

_SCUTTLEBUTT_KEYWORDS = (
    "customer",
    "customers",
    "pipeline",
    "backlog",
    "launch",
    "platform",
    "product",
    "adoption",
    "partnership",
    "developer",
    "enterprise",
    "客戶",
    "訂單",
    "產品",
    "平台",
    "合作",
    "採用",
    "研發",
)


@dataclass(frozen=True)
class FisherScore:
    long_term_growth_quality: list[ScoreLine] = field(default_factory=list)
    rd_commitment: list[ScoreLine] = field(default_factory=list)
    management_execution: list[ScoreLine] = field(default_factory=list)
    scuttlebutt_support: list[ScoreLine] = field(default_factory=list)
    revenue_cagr: float | None = None
    rd_intensity: float | None = None
    op_margin_sigma: float | None = None

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.long_term_growth_quality,
            self.rd_commitment,
            self.management_execution,
            self.scuttlebutt_support,
        )


def _long_term_growth_quality(
    metrics: list[FinancialMetrics],
) -> tuple[list[ScoreLine], float | None]:
    rev_points = [(f.period_end, f.revenue) for f in metrics if f.revenue and f.revenue > 0]
    rev_cagr, _, _, rev_desc = compute_cagr(rev_points, cap=0.40)
    latest_fm = latest(metrics)
    gm = latest_fm.gross_margin if latest_fm else None
    opm = latest_fm.operating_margin if latest_fm else None
    nis = [f.net_income for f in metrics if f.net_income is not None]

    lines = [
        ScoreLine(
            "Revenue CAGR > 10%",
            1.0 if rev_cagr is not None and rev_cagr > 0.10 else 0.0,
            1.0,
            f"revenue CAGR={pct(rev_cagr)} ({rev_desc})" if rev_cagr is not None else f"unavailable ({rev_desc})",
        ),
        ScoreLine(
            "Healthy margins",
            1.0 if (gm is not None and gm > 0.35) or (opm is not None and opm > 0.12) else 0.0,
            1.0,
            f"gross_margin={pct(gm)}, op_margin={pct(opm)}",
        ),
        ScoreLine(
            "Positive earnings in most years",
            1.0 if nis and sum(1 for v in nis if v > 0) >= max(1, len(nis) - 1) else 0.0,
            1.0,
            f"{sum(1 for v in nis if v > 0)}/{len(nis)} positive years" if nis else "no earnings history",
        ),
    ]
    return lines, rev_cagr


def _rd_commitment(
    line_items: list[LineItem],
    latest_fm: FinancialMetrics | None,
    news: list[CompanyNews],
) -> tuple[list[ScoreLine], float | None]:
    rd_series = line_item_series(line_items, "research_and_development")
    latest_rd = rd_series[0].value if rd_series and rd_series[0].value is not None else None
    revenue = latest_fm.revenue if latest_fm else None
    rd_intensity = latest_rd / revenue if latest_rd is not None and revenue not in (None, 0) else None

    recurring_points = sum(1 for item in rd_series if item.value is not None and item.value > 0)
    matched_titles = []
    for item in news:
        haystack = " ".join(filter(None, [item.title, item.summary])).lower()
        if any(kw.lower() in haystack for kw in _SCUTTLEBUTT_KEYWORDS):
            matched_titles.append(item.title)

    lines = [
        ScoreLine(
            "R&D / revenue > 5%",
            1.0 if rd_intensity is not None and rd_intensity > 0.05 else 0.0,
            1.0,
            f"R&D/revenue={pct(rd_intensity)} (R&D={money(latest_rd)})" if rd_intensity is not None else "R&D or revenue n/a",
        ),
        ScoreLine(
            "Recurring R&D or innovation-news support",
            1.0 if recurring_points >= 2 or matched_titles else 0.0,
            1.0,
            (
                f"R&D history points={recurring_points}; news matches={len(matched_titles)}"
                if rd_series or news
                else "no R&D history or news"
            ),
        ),
    ]
    return lines, rd_intensity


def _management_execution(
    metrics: list[FinancialMetrics],
    line_items: list[LineItem],
) -> tuple[list[ScoreLine], float | None]:
    op_margins = [f.operating_margin for f in metrics if f.operating_margin is not None]
    latest_fm = latest(metrics)
    roe = latest_fm.return_on_equity if latest_fm else None
    shares = line_item_series(line_items, "shares_outstanding")

    lines: list[ScoreLine] = []
    if len(op_margins) >= 3:
        sigma = pstdev(op_margins)
        improving = op_margins[-1] >= op_margins[0]
        lines.append(
            ScoreLine(
                "Op margin stable / improving",
                1.0 if sigma < 0.05 or improving else 0.0,
                1.0,
                f"sigma={pct(sigma)}; first={pct(op_margins[0])}, latest={pct(op_margins[-1])}",
            )
        )
    else:
        sigma = None
        lines.append(ScoreLine("Op margin stable / improving", 0.0, 1.0, f"<3 margin points ({len(op_margins)} available)"))

    lines.append(
        ScoreLine(
            "ROE > 12%",
            1.0 if roe is not None and roe > 0.12 else 0.0,
            1.0,
            f"ROE={pct(roe)}" if roe is not None else "ROE n/a",
        )
    )

    if len(shares) >= 2 and shares[0].value not in (None, 0) and shares[-1].value is not None:
        dilution = (shares[0].value - shares[-1].value) / shares[-1].value
        lines.append(
            ScoreLine(
                "No material dilution",
                1.0 if dilution <= 0.08 else 0.0,
                1.0,
                f"shares change={pct(dilution)} over observed history",
            )
        )
    else:
        lines.append(ScoreLine("No material dilution", 0.0, 1.0, "shares history insufficient"))
    return lines, sigma


def _scuttlebutt_support(
    news: list[CompanyNews],
    insider_trades: list[InsiderTrade],
) -> list[ScoreLine]:
    matched_titles = []
    for item in news:
        haystack = " ".join(filter(None, [item.title, item.summary])).lower()
        if any(kw.lower() in haystack for kw in _SCUTTLEBUTT_KEYWORDS):
            matched_titles.append(item.title)
    lines = [
        ScoreLine(
            "Product / customer / adoption news support",
            1.0 if matched_titles else 0.0,
            1.0,
            f"{len(matched_titles)} supportive news item(s)" if matched_titles else f"0 matches across {len(news)} news items",
        )
    ]

    if not insider_trades:
        lines.append(ScoreLine("Insider alignment", 0.0, 1.0, "no insider data"))
        return lines

    buy = sum(t.shares or 0 for t in insider_trades if t.transaction_type == "buy")
    sell = sum(abs(t.shares or 0) for t in insider_trades if t.transaction_type in ("sell", "planned_sell"))
    net = buy - sell
    lines.append(
        ScoreLine(
            "Insider alignment",
            1.0 if net >= 0 else 0.0,
            1.0,
            f"net delta={money(net)} ({'buying/flat' if net >= 0 else 'net selling'})",
        )
    )
    return lines


def score(state) -> FisherScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    insider: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    news: list[CompanyNews] = state.get("shared_data:company_news") or []
    sorted_metrics = sorted(metrics, key=lambda f: f.period_end) if metrics else []
    latest_fm = latest(metrics)

    growth_lines, rev_cagr = _long_term_growth_quality(sorted_metrics)
    rd_lines, rd_intensity = _rd_commitment(line_items, latest_fm, news)
    mgmt_lines, sigma = _management_execution(sorted_metrics, line_items)

    return FisherScore(
        long_term_growth_quality=growth_lines,
        rd_commitment=rd_lines,
        management_execution=mgmt_lines,
        scuttlebutt_support=_scuttlebutt_support(news, insider),
        revenue_cagr=rev_cagr,
        rd_intensity=rd_intensity,
        op_margin_sigma=sigma,
    )


def format_block(s: FisherScore) -> str:
    sections = [
        format_scorecard("Long-term Growth Quality", s.long_term_growth_quality),
        format_scorecard("R&D Commitment", s.rd_commitment),
        format_scorecard("Management Execution", s.management_execution),
        format_scorecard("Scuttlebutt Proxies", s.scuttlebutt_support),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  revenue_cagr: {pct(s.revenue_cagr)}\n"
        f"  rd_intensity: {pct(s.rd_intensity)}\n"
        f"  op_margin_sigma: {pct(s.op_margin_sigma)}"
    )
    return (
        "【Fisher 量化 checklist — durable growth + management execution + scuttlebutt proxies】\n"
        "這不是完整 scuttlebutt；它只是用公開財報、新聞與 insider 資料，替 Fisher 最在意的成長品質與管理層執行力建立弱代理。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
