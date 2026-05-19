"""Cathie Wood — disruptive platforms, long duration growth, innovation proxy.

Cathie Wood underwrites nonlinear outcomes from innovation platforms, but free
public data does not include TAM models or Wright's-law curves. This scorecard
therefore focuses on observable proxies: growth, reinvestment, disruptive-news
mentions, and whether valuation is at least somewhat anchored to growth.

  Disruptive platform fit (3)   Thematic keyword/news support (1) + revenue CAGR
                                > 20% (1) + R&D / revenue > 8% (1)
  Innovation reinvestment (2)   R&D history present (1) + gross margin > 40% or
                                op margin improving (1)
  Five-year growth runway (3)   Revenue CAGR > 25% (2) | > 15% (1) + price
                                momentum not deeply broken (1)
  Growth-adjusted valuation     P/S-to-growth < 0.5 (2) | < 1.0 (1)
    sanity (2)

Total cap 10. The persona still has to build the bull/base/bear narrative and
state clearly when TAM or learning-curve evidence is unavailable.
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
from alpha_council.providers.base import CompanyNews, FinancialMetrics, LineItem, PriceBar

_DISRUPTION_KEYWORDS = (
    "ai",
    "artificial intelligence",
    "machine learning",
    "autonomous",
    "robot",
    "genomics",
    "gene",
    "battery",
    "energy storage",
    "blockchain",
    "crypto",
    "space",
    "cloud",
    "platform",
    "software",
    "半導體",
    "人工智慧",
    "機器人",
    "基因",
    "儲能",
    "區塊鏈",
    "太空",
    "雲端",
    "平台",
)


@dataclass(frozen=True)
class CathieWoodScore:
    disruptive_platform_fit: list[ScoreLine] = field(default_factory=list)
    innovation_reinvestment: list[ScoreLine] = field(default_factory=list)
    five_year_growth_runway: list[ScoreLine] = field(default_factory=list)
    valuation_sanity: list[ScoreLine] = field(default_factory=list)
    revenue_cagr: float | None = None
    rd_intensity: float | None = None
    price_to_sales: float | None = None
    psg_ratio: float | None = None
    one_year_return: float | None = None

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.disruptive_platform_fit,
            self.innovation_reinvestment,
            self.five_year_growth_runway,
            self.valuation_sanity,
        )


def _news_matches(news: list[CompanyNews]) -> list[str]:
    matched_titles = []
    for item in news:
        haystack = " ".join(filter(None, [item.title, item.summary])).lower()
        if any(kw.lower() in haystack for kw in _DISRUPTION_KEYWORDS):
            matched_titles.append(item.title)
    return matched_titles


def _revenue_cagr(metrics: list[FinancialMetrics]) -> tuple[float | None, str]:
    rev_points = [(f.period_end, f.revenue) for f in metrics if f.revenue and f.revenue > 0]
    rev_cagr, _, _, rev_desc = compute_cagr(rev_points, cap=0.60)
    return rev_cagr, rev_desc


def _rd_intensity(line_items: list[LineItem], latest_fm: FinancialMetrics | None) -> tuple[float | None, int, float | None]:
    rd_series = line_item_series(line_items, "research_and_development")
    latest_rd = rd_series[0].value if rd_series and rd_series[0].value is not None else None
    revenue = latest_fm.revenue if latest_fm else None
    intensity = latest_rd / revenue if latest_rd is not None and revenue not in (None, 0) else None
    recurring_points = sum(1 for item in rd_series if item.value is not None and item.value > 0)
    return intensity, recurring_points, latest_rd


def _disruptive_platform_fit(
    revenue_cagr: float | None,
    rev_desc: str,
    rd_intensity: float | None,
    latest_rd: float | None,
    news: list[CompanyNews],
) -> list[ScoreLine]:
    matched_titles = _news_matches(news)
    return [
        ScoreLine(
            "Disruptive-theme news support",
            1.0 if matched_titles else 0.0,
            1.0,
            f"{len(matched_titles)} thematic news item(s)" if matched_titles else f"0 matches across {len(news)} news items",
        ),
        ScoreLine(
            "Revenue CAGR > 20%",
            1.0 if revenue_cagr is not None and revenue_cagr > 0.20 else 0.0,
            1.0,
            f"revenue CAGR={pct(revenue_cagr)} ({rev_desc})" if revenue_cagr is not None else f"unavailable ({rev_desc})",
        ),
        ScoreLine(
            "R&D / revenue > 8%",
            1.0 if rd_intensity is not None and rd_intensity > 0.08 else 0.0,
            1.0,
            f"R&D/revenue={pct(rd_intensity)} (R&D={money(latest_rd)})" if rd_intensity is not None else "R&D or revenue n/a",
        ),
    ]


def _innovation_reinvestment(
    metrics: list[FinancialMetrics],
    recurring_rd_points: int,
) -> list[ScoreLine]:
    latest_fm = latest(metrics)
    gm = latest_fm.gross_margin if latest_fm else None
    op_margins = [f.operating_margin for f in metrics if f.operating_margin is not None]
    improving = len(op_margins) >= 2 and op_margins[-1] > op_margins[0]
    return [
        ScoreLine(
            "Recurring R&D history",
            1.0 if recurring_rd_points >= 2 else 0.0,
            1.0,
            f"R&D history points={recurring_rd_points}",
        ),
        ScoreLine(
            "Healthy gross margin or improving op margin",
            1.0 if (gm is not None and gm > 0.40) or improving else 0.0,
            1.0,
            f"gross_margin={pct(gm)}; op_margin_trend={'improving' if improving else 'flat/declining'}",
        ),
    ]


def _five_year_growth_runway(
    revenue_cagr: float | None,
    prices: list[PriceBar],
) -> tuple[list[ScoreLine], float | None]:
    lines: list[ScoreLine] = []
    if revenue_cagr is None:
        lines.append(ScoreLine("Revenue CAGR > 25%", 0.0, 2.0, "revenue CAGR n/a"))
    else:
        score = 2.0 if revenue_cagr > 0.25 else (1.0 if revenue_cagr > 0.15 else 0.0)
        lines.append(ScoreLine("Revenue CAGR > 25%", score, 2.0, f"revenue CAGR={pct(revenue_cagr)}"))

    sorted_prices = sorted(prices, key=lambda p: p.bar_date)
    if len(sorted_prices) >= 2 and sorted_prices[0].close > 0:
        ret = sorted_prices[-1].close / sorted_prices[0].close - 1
        lines.append(
            ScoreLine(
                "Price momentum not deeply broken",
                1.0 if ret > -0.35 else 0.0,
                1.0,
                f"1y return={pct(ret)}",
            )
        )
    else:
        ret = None
        lines.append(ScoreLine("Price momentum not deeply broken", 0.0, 1.0, "price history insufficient"))
    return lines, ret


def _valuation_sanity(
    latest_fm: FinancialMetrics | None,
    market_cap: float | None,
    revenue_cagr: float | None,
) -> tuple[list[ScoreLine], float | None, float | None]:
    revenue = latest_fm.revenue if latest_fm else None
    if revenue in (None, 0) or market_cap in (None, 0):
        return [ScoreLine("P/S to growth", 0.0, 2.0, "revenue or market cap n/a")], None, None
    ps = market_cap / revenue
    if revenue_cagr is None or revenue_cagr <= 0:
        return [ScoreLine("P/S to growth", 0.0, 2.0, f"P/S={num(ps)}, growth={pct(revenue_cagr)} (undefined)")], ps, None
    psg = ps / (revenue_cagr * 100)
    score = 2.0 if psg < 0.5 else (1.0 if psg < 1.0 else 0.0)
    return [
        ScoreLine(
            "P/S to growth",
            score,
            2.0,
            f"P/S={num(ps)} / revenue growth={pct(revenue_cagr)} -> PSG={num(psg)}",
        )
    ], ps, psg


def score(state) -> CathieWoodScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    news: list[CompanyNews] = state.get("shared_data:company_news") or []
    prices: list[PriceBar] = state.get("shared_data:prices") or []
    market_cap = state.get("shared_data:market_cap")
    sorted_metrics = sorted(metrics, key=lambda f: f.period_end) if metrics else []
    latest_fm = latest(metrics)

    revenue_cagr, rev_desc = _revenue_cagr(sorted_metrics)
    rd_intensity, recurring_rd_points, latest_rd = _rd_intensity(line_items, latest_fm)
    runway_lines, one_year_return = _five_year_growth_runway(revenue_cagr, prices)
    valuation_lines, ps, psg = _valuation_sanity(latest_fm, market_cap, revenue_cagr)

    return CathieWoodScore(
        disruptive_platform_fit=_disruptive_platform_fit(revenue_cagr, rev_desc, rd_intensity, latest_rd, news),
        innovation_reinvestment=_innovation_reinvestment(sorted_metrics, recurring_rd_points),
        five_year_growth_runway=runway_lines,
        valuation_sanity=valuation_lines,
        revenue_cagr=revenue_cagr,
        rd_intensity=rd_intensity,
        price_to_sales=ps,
        psg_ratio=psg,
        one_year_return=one_year_return,
    )


def format_block(s: CathieWoodScore) -> str:
    sections = [
        format_scorecard("Disruptive Platform Fit", s.disruptive_platform_fit),
        format_scorecard("Innovation Reinvestment", s.innovation_reinvestment),
        format_scorecard("Five-year Growth Runway", s.five_year_growth_runway),
        format_scorecard("Growth-adjusted Valuation Sanity", s.valuation_sanity),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  revenue_cagr: {pct(s.revenue_cagr)}\n"
        f"  rd_intensity: {pct(s.rd_intensity)}\n"
        f"  price_to_sales: {num(s.price_to_sales)}\n"
        f"  psg_ratio: {num(s.psg_ratio)}\n"
        f"  one_year_return: {pct(s.one_year_return)}"
    )
    return (
        "【Cathie Wood 量化 checklist — disruptive innovation + long-duration growth proxies】\n"
        "這份 scorecard 只能用公開資料逼近 ARK 風格：它無法直接提供 TAM、Wright's Law 或 5 年平台市佔率，因此你必須在敘事中明說哪些關鍵假設仍未被資料驗證。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
