"""Nassim Taleb — fragility, tail risk, and convexity proxies.

Taleb's real framework leans on hidden exposures, optionality structure, and
regime change. Public fundamentals and yfinance prices cannot observe all of
that, so this scorecard stays explicit about what it *can* proxy:

  Balance-sheet fragility (3)   Low leverage (1) + strong liquidity (1) +
                                cash cushion vs debt (1)
  Tail-risk surface (3)         Annualized vol contained (1) + drawdown
                                contained (1) + worst daily loss not extreme (1)
  Convexity proxy (2)           52w upside/downside favorable (1) + positive
                                growth without leverage dependence (1)
  Skin in game + sentinel (2)   Insider alignment (1) + tail-risk headline
                                count low (1)

Total cap 10. High scores mean "less visibly fragile" under public data, not
"immune to black swans".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev

from alpha_council.masters._scoring.common import (
    ScoreLine,
    format_scorecard,
    latest,
    line_item_series,
    money,
    num,
    pct,
)
from alpha_council.providers.base import CompanyNews, FinancialMetrics, InsiderTrade, LineItem, PriceBar

_TAIL_RISK_KEYWORDS = (
    "accounting",
    "bankruptcy",
    "breach",
    "covenant",
    "credit",
    "cyber",
    "default",
    "disruption",
    "fraud",
    "investigation",
    "lawsuit",
    "liquidity",
    "recall",
    "refinancing",
    "regulatory",
    "sanction",
    "shortage",
    "supply chain",
    "tariff",
)


@dataclass(frozen=True)
class TalebScore:
    balance_sheet_fragility: list[ScoreLine] = field(default_factory=list)
    tail_risk_surface: list[ScoreLine] = field(default_factory=list)
    convexity_proxy: list[ScoreLine] = field(default_factory=list)
    skin_in_game_sentinel: list[ScoreLine] = field(default_factory=list)
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    cash_to_debt: float | None = None
    annualized_vol: float | None = None
    drawdown_pct: float | None = None
    worst_daily_return: float | None = None
    upside_downside_ratio: float | None = None
    revenue_growth_yoy: float | None = None
    current_price: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None

    @property
    def total(self) -> float:
        return sum(line.score for group in self._groups for line in group)

    @property
    def total_max(self) -> float:
        return sum(line.max_score for group in self._groups for line in group)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.balance_sheet_fragility,
            self.tail_risk_surface,
            self.convexity_proxy,
            self.skin_in_game_sentinel,
        )


def _sorted_prices(prices: list[PriceBar]) -> list[PriceBar]:
    return sorted(prices, key=lambda p: p.bar_date)


def _daily_returns(prices: list[PriceBar]) -> list[float]:
    closes = [p.close for p in _sorted_prices(prices) if p.close is not None and p.close > 0]
    returns: list[float] = []
    for prev, cur in zip(closes, closes[1:], strict=False):
        if prev <= 0:
            continue
        returns.append(cur / prev - 1)
    return returns


def _annualized_vol(prices: list[PriceBar]) -> float | None:
    returns = _daily_returns(prices)
    if len(returns) < 2:
        return None
    return pstdev(returns) * (252 ** 0.5)


def _drawdown(prices: list[PriceBar]) -> tuple[float | None, float | None, float | None, float | None]:
    if not prices:
        return None, None, None, None
    sorted_prices = _sorted_prices(prices)
    closes = [p.close for p in sorted_prices if p.close is not None]
    if not closes:
        return None, None, None, None
    current = sorted_prices[-1].close
    high = max(closes)
    low = min(closes)
    if current is None or high <= 0:
        return current, high, low, None
    return current, high, low, 1 - (current / high)


def _balance_sheet_fragility(latest_fm: FinancialMetrics | None, line_items: list[LineItem]) -> tuple[list[ScoreLine], float | None]:
    dte = latest_fm.debt_to_equity if latest_fm is not None else None
    current_ratio = latest_fm.current_ratio if latest_fm is not None else None
    debt_series = line_item_series(line_items, "total_debt")
    cash_series = line_item_series(line_items, "cash_and_equivalents")
    total_debt = debt_series[0].value if debt_series and debt_series[0].value is not None else None
    cash = cash_series[0].value if cash_series and cash_series[0].value is not None else None
    cash_to_debt = None if total_debt in (None, 0) else (cash / total_debt if cash is not None else None)

    lines: list[ScoreLine] = []
    lines.append(ScoreLine(
        "Debt-to-equity < 0.5",
        1.0 if dte is not None and dte < 0.5 else (0.5 if dte is not None and dte < 1.0 else 0.0),
        1.0,
        f"debt_to_equity={num(dte)}",
    ))
    lines.append(ScoreLine(
        "Current ratio > 1.5",
        1.0 if current_ratio is not None and current_ratio > 1.5 else (0.5 if current_ratio is not None and current_ratio > 1.0 else 0.0),
        1.0,
        f"current_ratio={num(current_ratio)}",
    ))
    if total_debt == 0 and cash is not None:
        lines.append(ScoreLine("Cash cushion vs debt", 1.0, 1.0, f"no debt; cash={money(cash)}"))
    else:
        lines.append(ScoreLine(
            "Cash cushion vs debt",
            1.0 if cash_to_debt is not None and cash_to_debt >= 0.5 else (0.5 if cash_to_debt is not None and cash_to_debt >= 0.2 else 0.0),
            1.0,
            f"cash={money(cash)} debt={money(total_debt)} ratio={num(cash_to_debt)}",
        ))
    return lines, cash_to_debt


def _tail_risk_surface(
    prices: list[PriceBar],
) -> tuple[list[ScoreLine], float | None, float | None, float | None, float | None, float | None, float | None]:
    current, high, low, drawdown_pct = _drawdown(prices)
    ann_vol = _annualized_vol(prices)
    returns = _daily_returns(prices)
    worst_day = min(returns) if returns else None

    lines: list[ScoreLine] = []
    lines.append(ScoreLine(
        "Annualized vol contained",
        1.0 if ann_vol is not None and ann_vol < 0.30 else (0.5 if ann_vol is not None and ann_vol < 0.45 else 0.0),
        1.0,
        f"annualized_vol={pct(ann_vol)}",
    ))
    lines.append(ScoreLine(
        "Drawdown from 52w high contained",
        1.0 if drawdown_pct is not None and drawdown_pct < 0.20 else (0.5 if drawdown_pct is not None and drawdown_pct < 0.35 else 0.0),
        1.0,
        f"drawdown={pct(drawdown_pct)}",
    ))
    lines.append(ScoreLine(
        "Worst daily loss not extreme",
        1.0 if worst_day is not None and worst_day > -0.05 else (0.5 if worst_day is not None and worst_day > -0.08 else 0.0),
        1.0,
        f"worst daily return={pct(worst_day)}",
    ))
    return lines, ann_vol, drawdown_pct, worst_day, current, high, low


def _convexity_proxy(latest_fm: FinancialMetrics | None, prices: list[PriceBar]) -> tuple[list[ScoreLine], float | None]:
    current, high, low, _ = _drawdown(prices)
    ratio = None
    if current not in (None, 0) and high is not None and low is not None and current > low:
        upside = max(high - current, 0.0)
        downside = current - low
        ratio = upside / downside if downside > 0 else None

    lines: list[ScoreLine] = []
    lines.append(ScoreLine(
        "Upside/downside ratio favorable",
        1.0 if ratio is not None and ratio > 1.5 else (0.5 if ratio is not None and ratio > 1.0 else 0.0),
        1.0,
        f"ratio={num(ratio)} using 52w range",
    ))

    growth = latest_fm.revenue_growth_yoy if latest_fm is not None else None
    dte = latest_fm.debt_to_equity if latest_fm is not None else None
    optionality = growth is not None and growth > 0 and dte is not None and dte < 0.5
    partial = (growth is not None and growth > 0) or (dte is not None and dte < 0.5)
    lines.append(ScoreLine(
        "Growth optionality without leverage dependence",
        1.0 if optionality else (0.5 if partial else 0.0),
        1.0,
        f"revenue_growth_yoy={pct(growth)} debt_to_equity={num(dte)}",
    ))
    return lines, ratio


def _insider_net_shares(insider_trades: list[InsiderTrade]) -> float | None:
    if not insider_trades:
        return None
    buys = sum((t.shares or 0.0) for t in insider_trades if t.transaction_type == "buy")
    sells = sum(abs(t.shares or 0.0) for t in insider_trades if t.transaction_type in ("sell", "planned_sell"))
    return buys - sells


def _tail_headline_count(news_items: list[CompanyNews]) -> int:
    count = 0
    for item in news_items:
        text = f"{item.title} {item.summary or ''}".lower()
        if any(keyword in text for keyword in _TAIL_RISK_KEYWORDS):
            count += 1
    return count


def _skin_in_game_sentinel(insider_trades: list[InsiderTrade], news_items: list[CompanyNews]) -> list[ScoreLine]:
    lines: list[ScoreLine] = []
    net_shares = _insider_net_shares(insider_trades)
    if net_shares is None:
        lines.append(ScoreLine("Insider skin in the game", 0.0, 1.0, "no insider data"))
    else:
        score = 1.0 if net_shares >= 0 else 0.0
        verdict = "net buying / neutral" if net_shares >= 0 else "net selling"
        lines.append(ScoreLine(
            "Insider skin in the game",
            score,
            1.0,
            f"net insider shares={num(net_shares)} ({verdict})",
        ))

    if not news_items:
        lines.append(ScoreLine("Black swan sentinel headlines", 0.0, 1.0, "no recent news"))
    else:
        tail_count = _tail_headline_count(news_items)
        score = 1.0 if tail_count == 0 else (0.5 if tail_count == 1 else 0.0)
        lines.append(ScoreLine(
            "Black swan sentinel headlines",
            score,
            1.0,
            f"tail-risk headline count={tail_count}",
        ))
    return lines


def score(state) -> TalebScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    insider: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    news_items: list[CompanyNews] = state.get("shared_data:company_news") or []
    prices: list[PriceBar] = state.get("shared_data:prices") or []

    latest_fm = latest(metrics)
    balance_lines, cash_to_debt = _balance_sheet_fragility(latest_fm, line_items)
    tail_lines, ann_vol, drawdown_pct, worst_day, current, high, low = _tail_risk_surface(prices)
    convexity_lines, ratio = _convexity_proxy(latest_fm, prices)

    return TalebScore(
        balance_sheet_fragility=balance_lines,
        tail_risk_surface=tail_lines,
        convexity_proxy=convexity_lines,
        skin_in_game_sentinel=_skin_in_game_sentinel(insider, news_items),
        debt_to_equity=latest_fm.debt_to_equity if latest_fm is not None else None,
        current_ratio=latest_fm.current_ratio if latest_fm is not None else None,
        cash_to_debt=cash_to_debt,
        annualized_vol=ann_vol,
        drawdown_pct=drawdown_pct,
        worst_daily_return=worst_day,
        upside_downside_ratio=ratio,
        revenue_growth_yoy=latest_fm.revenue_growth_yoy if latest_fm is not None else None,
        current_price=current,
        high_52w=high,
        low_52w=low,
    )


def format_block(s: TalebScore) -> str:
    sections = [
        format_scorecard("Balance-sheet Fragility", s.balance_sheet_fragility),
        format_scorecard("Tail-risk Surface", s.tail_risk_surface),
        format_scorecard("Convexity Proxy", s.convexity_proxy),
        format_scorecard("Skin in the Game + Sentinel", s.skin_in_game_sentinel),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  debt_to_equity: {num(s.debt_to_equity)}\n"
        f"  current_ratio: {num(s.current_ratio)}\n"
        f"  cash_to_debt: {num(s.cash_to_debt)}\n"
        f"  annualized_vol: {pct(s.annualized_vol)}\n"
        f"  drawdown_pct: {pct(s.drawdown_pct)}\n"
        f"  worst_daily_return: {pct(s.worst_daily_return)}\n"
        f"  upside_downside_ratio: {num(s.upside_downside_ratio)}\n"
        f"  revenue_growth_yoy: {pct(s.revenue_growth_yoy)}\n"
        f"  current_price: {num(s.current_price)}\n"
        f"  52w_high: {num(s.high_52w)}\n"
        f"  52w_low: {num(s.low_52w)}"
    )
    return (
        "【Taleb 量化 checklist — fragility + tail-risk + convexity proxy】\n"
        "這是用公開財務與價格資料建立的 proxy scorecard。高分只代表『較不脆弱、較少可見尾部風險』，不是黑天鵝免疫。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
