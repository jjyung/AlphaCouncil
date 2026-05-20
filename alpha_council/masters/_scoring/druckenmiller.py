"""Stanley Druckenmiller — growth, momentum, and asymmetric payoff.

This scorecard is intentionally public-data-only. It cannot observe true macro
book positioning, cross-asset flows, or proprietary catalyst work, so it uses
three observable proxies instead:

  Growth acceleration (3)    Revenue CAGR > 15% (1) + earnings CAGR > 20% (1)
                            + earnings outgrowing revenue (1)
  Momentum + trend (3)      1Y return strong (1.5) + 6M return positive (1)
                            + current price near 52w high (0.5)
  Asymmetric setup (2)      52w upside/downside ratio favorable (1) +
                            annualized vol manageable (1)
  Confirmation (2)          Insider net buying (1) + positive catalyst news (1)

Total cap 10. The LLM should use this as the hard screen, then layer in the
qualitative macro narrative from the analyst reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from statistics import pstdev

from alpha_council.masters._scoring.common import (
    ScoreLine,
    compute_cagr,
    format_scorecard,
    money,
    num,
    pct,
)
from alpha_council.providers.base import CompanyNews, FinancialMetrics, InsiderTrade, PriceBar

_POSITIVE_NEWS_KEYWORDS = (
    "adoption",
    "approval",
    "backlog",
    "contract",
    "demand",
    "expansion",
    "growth",
    "guidance",
    "launch",
    "margin",
    "partnership",
    "platform",
    "rollout",
    "upgrade",
)
_NEGATIVE_NEWS_KEYWORDS = (
    "delay",
    "downgrade",
    "fraud",
    "investigation",
    "lawsuit",
    "miss",
    "recall",
    "restructuring",
    "warning",
)


@dataclass(frozen=True)
class DruckenmillerScore:
    growth_acceleration: list[ScoreLine] = field(default_factory=list)
    momentum_trend: list[ScoreLine] = field(default_factory=list)
    asymmetric_setup: list[ScoreLine] = field(default_factory=list)
    confirmation: list[ScoreLine] = field(default_factory=list)
    revenue_cagr: float | None = None
    earnings_cagr: float | None = None
    one_year_return: float | None = None
    six_month_return: float | None = None
    annualized_vol: float | None = None
    upside_downside_ratio: float | None = None
    current_price: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    market_cap: float | None = None

    @property
    def total(self) -> float:
        return sum(line.score for group in self._groups for line in group)

    @property
    def total_max(self) -> float:
        return sum(line.max_score for group in self._groups for line in group)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.growth_acceleration,
            self.momentum_trend,
            self.asymmetric_setup,
            self.confirmation,
        )


def _sorted_prices(prices: list[PriceBar]) -> list[PriceBar]:
    return sorted(prices, key=lambda p: p.bar_date)


def _return_since(prices: list[PriceBar], days: int) -> float | None:
    if len(prices) < 2:
        return None
    sorted_prices = _sorted_prices(prices)
    end = sorted_prices[-1]
    if end.close is None or end.close <= 0:
        return None
    cutoff = end.bar_date - timedelta(days=days)
    start = next((p for p in sorted_prices if p.bar_date >= cutoff and p.close is not None and p.close > 0), None)
    if start is None:
        start = next((p for p in sorted_prices if p.close is not None and p.close > 0), None)
    if start is None or start.close is None or start.close <= 0 or start.bar_date == end.bar_date:
        return None
    return end.close / start.close - 1


def _annualized_vol(prices: list[PriceBar]) -> float | None:
    sorted_prices = _sorted_prices(prices)
    closes = [p.close for p in sorted_prices if p.close is not None and p.close > 0]
    if len(closes) < 3:
        return None
    returns = []
    for prev, cur in zip(closes, closes[1:], strict=False):
        if prev <= 0:
            continue
        returns.append(cur / prev - 1)
    if len(returns) < 2:
        return None
    return pstdev(returns) * (252 ** 0.5)


def _growth_acceleration(metrics: list[FinancialMetrics]) -> tuple[list[ScoreLine], float | None, float | None]:
    rev_points = [(m.period_end, m.revenue) for m in metrics if m.revenue is not None and m.revenue > 0]
    ni_points = [(m.period_end, m.net_income) for m in metrics if m.net_income is not None and m.net_income > 0]
    rev_cagr, _, _, rev_desc = compute_cagr(rev_points, cap=0.60)
    ni_cagr, _, _, ni_desc = compute_cagr(ni_points, cap=0.60)

    lines: list[ScoreLine] = []
    lines.append(ScoreLine(
        "Revenue CAGR > 15%",
        1.0 if rev_cagr is not None and rev_cagr > 0.15 else 0.0,
        1.0,
        f"revenue CAGR={pct(rev_cagr)} ({rev_desc})" if rev_cagr is not None else f"unavailable ({rev_desc})",
    ))
    lines.append(ScoreLine(
        "Earnings CAGR > 20%",
        1.0 if ni_cagr is not None and ni_cagr > 0.20 else 0.0,
        1.0,
        f"earnings CAGR={pct(ni_cagr)} ({ni_desc})" if ni_cagr is not None else f"unavailable ({ni_desc})",
    ))
    if rev_cagr is None or ni_cagr is None:
        lines.append(ScoreLine(
            "Earnings outgrowing revenue",
            0.0,
            1.0,
            "need both revenue and earnings CAGR",
        ))
    else:
        spread = ni_cagr - rev_cagr
        lines.append(ScoreLine(
            "Earnings outgrowing revenue",
            1.0 if spread > 0.05 else 0.0,
            1.0,
            f"earnings CAGR {pct(ni_cagr)} vs revenue CAGR {pct(rev_cagr)} (spread={pct(spread)})",
        ))
    return lines, rev_cagr, ni_cagr


def _momentum_trend(prices: list[PriceBar]) -> tuple[list[ScoreLine], float | None, float | None, float | None, float | None, float | None]:
    if not prices:
        empty = [
            ScoreLine("1Y return strong", 0.0, 1.5, "no price history"),
            ScoreLine("6M trend positive", 0.0, 1.0, "no price history"),
            ScoreLine("Current price near 52w high", 0.0, 0.5, "no price history"),
        ]
        return empty, None, None, None, None, None

    sorted_prices = _sorted_prices(prices)
    current = sorted_prices[-1].close
    closes = [p.close for p in sorted_prices if p.close is not None]
    high = max(closes) if closes else None
    low = min(closes) if closes else None
    one_year_return = _return_since(prices, 365)
    six_month_return = _return_since(prices, 183)

    lines: list[ScoreLine] = []
    if one_year_return is None:
        lines.append(ScoreLine("1Y return strong", 0.0, 1.5, "insufficient history"))
    else:
        score = 1.5 if one_year_return > 0.20 else (1.0 if one_year_return > 0.10 else (0.5 if one_year_return > 0 else 0.0))
        lines.append(ScoreLine("1Y return strong", score, 1.5, f"1Y return={pct(one_year_return)}"))

    if six_month_return is None:
        lines.append(ScoreLine("6M trend positive", 0.0, 1.0, "insufficient history"))
    else:
        score = 1.0 if six_month_return > 0.10 else (0.5 if six_month_return > 0 else 0.0)
        lines.append(ScoreLine("6M trend positive", score, 1.0, f"6M return={pct(six_month_return)}"))

    if current is None or high in (None, 0):
        lines.append(ScoreLine("Current price near 52w high", 0.0, 0.5, "current/high unavailable"))
    else:
        distance = current / high - 1
        score = 0.5 if distance >= -0.15 else (0.25 if distance >= -0.25 else 0.0)
        lines.append(ScoreLine(
            "Current price near 52w high",
            score,
            0.5,
            f"current={num(current)} vs 52w high={num(high)} (distance={pct(distance)})",
        ))
    return lines, one_year_return, six_month_return, current, high, low


def _asymmetric_setup(prices: list[PriceBar]) -> tuple[list[ScoreLine], float | None, float | None]:
    if not prices:
        return ([ScoreLine("Favorable upside/downside + vol", 0.0, 2.0, "no price history")], None, None)

    sorted_prices = _sorted_prices(prices)
    current = sorted_prices[-1].close
    closes = [p.close for p in sorted_prices if p.close is not None]
    high = max(closes) if closes else None
    low = min(closes) if closes else None
    vol = _annualized_vol(prices)
    if current in (None, 0) or high is None or low is None or current <= low:
        return ([ScoreLine("Favorable upside/downside + vol", 0.0, 2.0, "current/high/low unavailable")], vol, None)

    upside = max(high - current, 0.0)
    downside = current - low
    ratio = upside / downside if downside > 0 else None
    if ratio is None or vol is None:
        return ([ScoreLine(
            "Favorable upside/downside + vol",
            0.0,
            2.0,
            f"ratio={num(ratio)} vol={pct(vol)} (need both ratio and volatility)",
        )], vol, ratio)

    if ratio > 1.5 and vol < 0.45:
        score, verdict = 2.0, "clear asymmetry"
    elif ratio > 1.0 and vol < 0.60:
        score, verdict = 1.0, "acceptable asymmetry"
    else:
        score, verdict = 0.0, "crowded or too volatile"
    return ([ScoreLine(
        "Favorable upside/downside + vol",
        score,
        2.0,
        f"upside={money(upside)} downside={money(downside)} ratio={num(ratio)}; ann vol={pct(vol)} ({verdict})",
    )], vol, ratio)


def _insider_net_shares(insider_trades: list[InsiderTrade]) -> float | None:
    if not insider_trades:
        return None
    buys = sum((t.shares or 0.0) for t in insider_trades if t.transaction_type == "buy")
    sells = sum(abs(t.shares or 0.0) for t in insider_trades if t.transaction_type in ("sell", "planned_sell"))
    return buys - sells


def _news_balance(news_items: list[CompanyNews]) -> tuple[int, int]:
    positive = 0
    negative = 0
    for item in news_items:
        text = f"{item.title} {item.summary or ''}".lower()
        if any(keyword in text for keyword in _POSITIVE_NEWS_KEYWORDS):
            positive += 1
        if any(keyword in text for keyword in _NEGATIVE_NEWS_KEYWORDS):
            negative += 1
    return positive, negative


def _confirmation(insider_trades: list[InsiderTrade], news_items: list[CompanyNews]) -> list[ScoreLine]:
    lines: list[ScoreLine] = []
    net_shares = _insider_net_shares(insider_trades)
    if net_shares is None:
        lines.append(ScoreLine("Insider confirmation", 0.0, 1.0, "no insider data"))
    else:
        lines.append(ScoreLine(
            "Insider confirmation",
            1.0 if net_shares > 0 else 0.0,
            1.0,
            f"net insider shares={num(net_shares)}",
        ))

    if not news_items:
        lines.append(ScoreLine("Catalyst news confirmation", 0.0, 1.0, "no recent news"))
    else:
        positive, negative = _news_balance(news_items)
        lines.append(ScoreLine(
            "Catalyst news confirmation",
            1.0 if positive > negative else 0.0,
            1.0,
            f"positive catalysts={positive}, negative headlines={negative}",
        ))
    return lines


def score(state) -> DruckenmillerScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    insider: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    news_items: list[CompanyNews] = state.get("shared_data:company_news") or []
    prices: list[PriceBar] = state.get("shared_data:prices") or []
    market_cap = state.get("shared_data:market_cap")

    sorted_metrics = sorted(metrics, key=lambda m: m.period_end)
    growth_lines, rev_cagr, ni_cagr = _growth_acceleration(sorted_metrics)
    momentum_lines, one_year_return, six_month_return, current, high, low = _momentum_trend(prices)
    asym_lines, ann_vol, ratio = _asymmetric_setup(prices)

    return DruckenmillerScore(
        growth_acceleration=growth_lines,
        momentum_trend=momentum_lines,
        asymmetric_setup=asym_lines,
        confirmation=_confirmation(insider, news_items),
        revenue_cagr=rev_cagr,
        earnings_cagr=ni_cagr,
        one_year_return=one_year_return,
        six_month_return=six_month_return,
        annualized_vol=ann_vol,
        upside_downside_ratio=ratio,
        current_price=current,
        high_52w=high,
        low_52w=low,
        market_cap=market_cap,
    )


def format_block(s: DruckenmillerScore) -> str:
    sections = [
        format_scorecard("Growth Acceleration", s.growth_acceleration),
        format_scorecard("Momentum + Trend", s.momentum_trend),
        format_scorecard("Asymmetric Setup", s.asymmetric_setup),
        format_scorecard("Confirmation", s.confirmation),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  revenue_cagr: {pct(s.revenue_cagr)}\n"
        f"  earnings_cagr: {pct(s.earnings_cagr)}\n"
        f"  one_year_return: {pct(s.one_year_return)}\n"
        f"  six_month_return: {pct(s.six_month_return)}\n"
        f"  annualized_vol: {pct(s.annualized_vol)}\n"
        f"  upside_downside_ratio: {num(s.upside_downside_ratio)}\n"
        f"  current_price: {num(s.current_price)}\n"
        f"  52w_high: {num(s.high_52w)}\n"
        f"  52w_low: {num(s.low_52w)}\n"
        f"  market_cap: {money(s.market_cap)}"
    )
    return (
        "【Druckenmiller 量化 checklist — growth + momentum + asymmetric upside】\n"
        "這是 public-data-only 的第一版代理分數。它能驗證成長、價格趨勢與風險報酬 proxy，但無法直接觀察真正的宏觀資金流與跨資產部位。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
