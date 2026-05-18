"""Charlie Munger — high-quality businesses at a fair price.

Munger differs from Buffett mostly in *how much he insists on quality*:
he pays up for great businesses and is much less interested in deep
discounts to book value. The scoring leans heavier on moat / predictability
and lighter on margin-of-safety than Buffett.

  Predictability (max 3)  OCF positive 5y (3) | 3-4y (1)
  Moat quality (max 4)    Gross margin > 40% (2) | Op margin > 20% (2)
  Capital efficiency (3)  ROIC > 15% (3) | > 10% (1) | fallback ROE > 20% (2)
  Balance sheet (2)       D/E < 0.5 (2) | < 1.0 (1)
  Capital allocation (2)  Net buybacks (1) | Insider net buying (1)
  Management quality (2)  Capital intensity (CapEx/Rev < 10%) (1) |
                          Reasonable payout (1) — dividends+buybacks/NI ∈ [20%, 80%]
  Valuation (2)           OE yield > 5% (2) | > 3% (1)

Total cap 18. Munger tolerates a richer valuation than Buffett does, hence
the more generous OE-yield thresholds. Management quality sits separately
from "capital allocation" because the latter just checks buyback direction,
while quality looks at *whether reinvestment is disciplined*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from alpha_council.masters._scoring.common import (
    ScoreLine,
    compute_owner_earnings,
    format_scorecard,
    latest,
    line_item_series,
    money,
    num,
    pct,
)
from alpha_council.providers.base import FinancialMetrics, InsiderTrade, LineItem


@dataclass(frozen=True)
class MungerScore:
    predictability: list[ScoreLine] = field(default_factory=list)
    moat: list[ScoreLine] = field(default_factory=list)
    capital_efficiency: list[ScoreLine] = field(default_factory=list)
    balance_sheet: list[ScoreLine] = field(default_factory=list)
    capital_allocation: list[ScoreLine] = field(default_factory=list)
    management_quality: list[ScoreLine] = field(default_factory=list)
    valuation: list[ScoreLine] = field(default_factory=list)
    intrinsic_value: float | None = None
    market_cap: float | None = None
    margin_of_safety: float | None = None
    owner_earnings_yield: float | None = None

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.predictability,
            self.moat,
            self.capital_efficiency,
            self.balance_sheet,
            self.capital_allocation,
            self.management_quality,
            self.valuation,
        )


def _predictability(line_items: Iterable[LineItem]) -> list[ScoreLine]:
    ocf_series = list(line_item_series(list(line_items), "operating_cash_flow"))
    if not ocf_series:
        return [ScoreLine("OCF positive (5y)", 0.0, 3.0, "OCF history unavailable")]
    positives = sum(1 for li in ocf_series if (li.value or 0) > 0)
    score = 3.0 if positives >= 5 else (1.0 if positives >= 3 else 0.0)
    return [ScoreLine("OCF positive (5y)", score, 3.0,
                       f"{positives}/{len(ocf_series)} positive years")]


def _moat(latest_fm: FinancialMetrics | None) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("Moat quality", 0.0, 4.0, "no recent metrics")]
    gm = latest_fm.gross_margin
    om = latest_fm.operating_margin
    lines = []
    lines.append(ScoreLine(
        "Gross margin > 40%",
        2.0 if (gm is not None and gm > 0.40) else (1.0 if (gm is not None and gm > 0.25) else 0.0),
        2.0,
        f"gross_margin={pct(gm)}" if gm is not None else "gross margin n/a",
    ))
    lines.append(ScoreLine(
        "Op margin > 20%",
        2.0 if (om is not None and om > 0.20) else (1.0 if (om is not None and om > 0.12) else 0.0),
        2.0,
        f"op_margin={pct(om)}" if om is not None else "op margin n/a",
    ))
    return lines


def _capital_efficiency(latest_fm: FinancialMetrics | None) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("ROIC (or ROE fallback)", 0.0, 3.0, "no recent metrics")]
    roic = latest_fm.return_on_invested_capital
    if roic is not None:
        score = 3.0 if roic > 0.15 else (1.0 if roic > 0.10 else 0.0)
        return [ScoreLine("ROIC > 15%", score, 3.0, f"ROIC={pct(roic)}")]
    # Fallback to ROE when ROIC missing (TW data often lacks 'Invested Capital').
    roe = latest_fm.return_on_equity
    if roe is None:
        return [ScoreLine("ROIC / ROE", 0.0, 3.0, "both unavailable")]
    score = 2.0 if roe > 0.20 else (1.0 if roe > 0.10 else 0.0)
    return [ScoreLine("ROE > 20% (ROIC fallback)", score, 3.0, f"ROE={pct(roe)} (ROIC n/a)")]


def _balance_sheet(latest_fm: FinancialMetrics | None) -> list[ScoreLine]:
    if latest_fm is None or latest_fm.debt_to_equity is None:
        return [ScoreLine("D/E < 0.5", 0.0, 2.0, "D/E n/a")]
    de = latest_fm.debt_to_equity
    score = 2.0 if de < 0.5 else (1.0 if de < 1.0 else 0.0)
    return [ScoreLine("D/E < 0.5", score, 2.0, f"D/E={num(de)}")]


def _capital_allocation(line_items: Iterable[LineItem],
                         insider_trades: list[InsiderTrade]) -> list[ScoreLine]:
    lines = []
    shares = list(line_item_series(list(line_items), "shares_outstanding"))
    if len(shares) >= 2 and shares[0].value is not None and shares[-1].value is not None:
        delta = shares[0].value - shares[-1].value
        lines.append(ScoreLine(
            "Net buybacks",
            1.0 if delta < 0 else 0.0,
            1.0,
            f"shares {money(shares[-1].value)} → {money(shares[0].value)}",
        ))
    else:
        lines.append(ScoreLine("Net buybacks", 0.0, 1.0, "shares-outstanding history n/a"))

    if not insider_trades:
        lines.append(ScoreLine("Insider net buying", 0.0, 1.0, "no insider data"))
    else:
        buy = sum(t.shares or 0 for t in insider_trades if t.transaction_type == "buy")
        sell = sum(abs(t.shares or 0) for t in insider_trades
                   if t.transaction_type in ("sell", "planned_sell"))
        net = buy - sell
        lines.append(ScoreLine(
            "Insider net buying",
            1.0 if net > 0 else 0.0,
            1.0,
            f"net Δ={money(net)} shares across {len(insider_trades)} rows",
        ))
    return lines


def _management_quality(latest_fm: FinancialMetrics | None,
                         line_items: Iterable[LineItem]) -> list[ScoreLine]:
    """Capital intensity + payout discipline.

    These two together capture "is management deploying capital sensibly?":
      - Capital intensity = abs(CapEx) / Revenue. Lower is better for moat
        businesses (think See's Candies). Above ~10% suggests heavy capex
        treadmill, which Munger dislikes.
      - Payout ratio = (abs(dividends_paid) + abs(net buyback spend)) / NI.
        We can't observe buyback spend cleanly, so we use dividends_paid
        only. "Reasonable" band 20%-80% — too low = hoarding, too high =
        starved of reinvestment.
    """
    if latest_fm is None:
        return [ScoreLine("Management quality", 0.0, 2.0, "no metrics")]
    items_list = list(line_items)
    capex_series = line_item_series(items_list, "capital_expenditure")
    capex = capex_series[0].value if capex_series and capex_series[0].value is not None else None
    revenue = latest_fm.revenue
    lines: list[ScoreLine] = []
    if capex is not None and revenue and revenue > 0:
        intensity = abs(capex) / revenue
        score = 1.0 if intensity < 0.10 else 0.0
        lines.append(ScoreLine(
            "Capital intensity (CapEx/Rev < 10%)",
            score, 1.0,
            f"CapEx/Rev={pct(intensity)} ({money(capex)}/{money(revenue)})",
        ))
    else:
        lines.append(ScoreLine("Capital intensity", 0.0, 1.0, "CapEx or revenue n/a"))

    div_series = line_item_series(items_list, "dividends_paid")
    div = div_series[0].value if div_series and div_series[0].value is not None else None
    ni = latest_fm.net_income
    if div is not None and ni and ni > 0:
        payout = abs(div) / ni
        if 0.20 <= payout <= 0.80:
            score = 1.0
            verdict = "in band"
        elif payout < 0.20:
            score = 0.0
            verdict = "hoarding (<20%)"
        else:
            score = 0.0
            verdict = "over-distributing (>80%)"
        lines.append(ScoreLine(
            "Payout ratio in [20%, 80%]",
            score, 1.0,
            f"payout={pct(payout)} → {verdict}",
        ))
    else:
        lines.append(ScoreLine("Payout ratio", 0.0, 1.0,
                                "dividends_paid or net income n/a"))
    return lines


def _valuation(latest_fm: FinancialMetrics | None,
                line_items: Iterable[LineItem],
                market_cap: float | None) -> tuple[list[ScoreLine], float | None, float | None, float | None]:
    """Munger's intrinsic = OE × 12 (slightly richer than Buffett's 10x — he
    pays up for predictability/quality)."""
    owner_earnings, derivation = compute_owner_earnings(latest_fm, line_items)
    if owner_earnings is None or market_cap is None or market_cap == 0:
        return [ScoreLine("OE yield > 5%", 0.0, 2.0,
                          f"{derivation}; market_cap={money(market_cap)}")], None, None, None
    oe_yield = owner_earnings / market_cap
    intrinsic = owner_earnings * 12
    mos = (intrinsic - market_cap) / intrinsic if intrinsic > 0 else None
    score = 2.0 if oe_yield > 0.05 else (1.0 if oe_yield > 0.03 else 0.0)
    return (
        [ScoreLine("OE yield > 5%", score, 2.0,
                   f"OE yield={pct(oe_yield)}; intrinsic≈{money(intrinsic)}; MoS={pct(mos)}")],
        intrinsic,
        oe_yield,
        mos,
    )


def score(state) -> MungerScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    insider: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    market_cap = state.get("shared_data:market_cap")
    latest_fm = latest(metrics)
    val, intrinsic, oe_yield, mos = _valuation(latest_fm, line_items, market_cap)
    return MungerScore(
        predictability=_predictability(line_items),
        moat=_moat(latest_fm),
        capital_efficiency=_capital_efficiency(latest_fm),
        balance_sheet=_balance_sheet(latest_fm),
        capital_allocation=_capital_allocation(line_items, insider),
        management_quality=_management_quality(latest_fm, line_items),
        valuation=val,
        intrinsic_value=intrinsic,
        market_cap=market_cap,
        margin_of_safety=mos,
        owner_earnings_yield=oe_yield,
    )


def format_block(s: MungerScore) -> str:
    sections = [
        format_scorecard("Predictability", s.predictability),
        format_scorecard("Moat Quality", s.moat),
        format_scorecard("Capital Efficiency", s.capital_efficiency),
        format_scorecard("Balance Sheet", s.balance_sheet),
        format_scorecard("Capital Allocation", s.capital_allocation),
        format_scorecard("Management Quality", s.management_quality),
        format_scorecard("Valuation (OE × 12)", s.valuation),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  intrinsic_value: {money(s.intrinsic_value)}\n"
        f"  market_cap: {money(s.market_cap)}\n"
        f"  margin_of_safety: {pct(s.margin_of_safety)}\n"
        f"  owner_earnings_yield: {pct(s.owner_earnings_yield)}"
    )
    return (
        "【Munger 量化 checklist — 高品質企業合理價，重 predictability 與 ROIC】\n"
        "n/a 表示資料源未提供，請在敘事中標記為「未驗證」，不可主觀補值。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
