"""Warren Buffett — deterministic checklist score.

Adapted from ai-hedge-fund's analyse_buffett with these mapping choices:

  Profitability (max 6)   ROE>15% (2) | Op-margin>15% (2) | Net-margin>10% (1) | ROA>5% (1)
  Financial strength (4)  D/E<0.5 (2)  | Current ratio>1.5 (1) | FCF positive (1)
  Earnings quality (3)    Net income positive 5y (2) | Earnings growing YoY (1)
  Pricing power (2)       Gross margin > 40% (1) | Gross margin stable (1)
  Compounding (2)         BVPS 4y CAGR > 10% (2) | > 5% (1)
  Moat proxy (3)          ROE std dev <5pp over 5y (2) | Margin stability (1)
  Management (2)          Net buybacks (1) | Insider net buying (1)
  Valuation (2)           Owner Earnings yield > 6% on current market cap (2)

Total cap 24 points.

Pricing power vs moat proxy: moat proxy measures *stability* of returns;
pricing power measures the *underlying source* — a high gross margin says
the firm can charge a premium before SG&A even kicks in, which is the
upstream evidence Buffett actually looks for ("the ability to raise prices
with little loss of customers").

Compounding: BVPS growth is Buffett's classic single-number proxy for
intrinsic value compounding ("annual percentage change in book value"). The score itself is not the recommendation — it feeds
the LLM persona, which weighs it against analyst-report qualitative signals
before issuing the final 買入 / 持有 / 不碰. We keep the cap public so the
LLM can sanity-check whether scoring inputs were complete.

`format_block` is what gets injected into Warren's system_instruction; it
deliberately appears in the *master-specific tail* (per master_runtime.py
caching design) since the numbers are unique to each master.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev
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
class BuffettScore:
    profitability: list[ScoreLine] = field(default_factory=list)
    financial_strength: list[ScoreLine] = field(default_factory=list)
    earnings_quality: list[ScoreLine] = field(default_factory=list)
    pricing_power: list[ScoreLine] = field(default_factory=list)
    compounding: list[ScoreLine] = field(default_factory=list)
    moat: list[ScoreLine] = field(default_factory=list)
    management: list[ScoreLine] = field(default_factory=list)
    valuation: list[ScoreLine] = field(default_factory=list)
    intrinsic_value: float | None = None
    market_cap: float | None = None
    margin_of_safety: float | None = None
    owner_earnings_yield: float | None = None
    bvps_cagr: float | None = None

    @property
    def _groups(self) -> tuple[list[ScoreLine], ...]:
        return (
            self.profitability,
            self.financial_strength,
            self.earnings_quality,
            self.pricing_power,
            self.compounding,
            self.moat,
            self.management,
            self.valuation,
        )

    @property
    def total(self) -> float:
        return sum(l.score for g in self._groups for l in g)

    @property
    def total_max(self) -> float:
        return sum(l.max_score for g in self._groups for l in g)


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------


def _profitability(latest_fm: FinancialMetrics | None) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("Profitability", 0.0, 6.0, "no recent financial metrics available")]
    lines: list[ScoreLine] = []

    roe = latest_fm.return_on_equity
    if roe is None:
        lines.append(ScoreLine("ROE > 15%", 0.0, 2.0, "ROE n/a"))
    else:
        lines.append(ScoreLine("ROE > 15%", 2.0 if roe > 0.15 else (1.0 if roe > 0.08 else 0.0),
                               2.0, f"ROE={pct(roe)}"))

    om = latest_fm.operating_margin
    if om is None:
        lines.append(ScoreLine("Op margin > 15%", 0.0, 2.0, "operating margin n/a"))
    else:
        lines.append(ScoreLine("Op margin > 15%", 2.0 if om > 0.15 else (1.0 if om > 0.08 else 0.0),
                               2.0, f"op_margin={pct(om)}"))

    nm = latest_fm.net_margin
    lines.append(ScoreLine(
        "Net margin > 10%",
        1.0 if (nm is not None and nm > 0.10) else 0.0,
        1.0,
        f"net_margin={pct(nm)}" if nm is not None else "net margin n/a",
    ))

    roa = latest_fm.return_on_assets
    lines.append(ScoreLine(
        "ROA > 5%",
        1.0 if (roa is not None and roa > 0.05) else 0.0,
        1.0,
        f"ROA={pct(roa)}" if roa is not None else "ROA n/a",
    ))
    return lines


def _financial_strength(latest_fm: FinancialMetrics | None,
                         line_items: Iterable[LineItem]) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("Financial strength", 0.0, 4.0, "no recent financial metrics available")]
    lines: list[ScoreLine] = []

    de = latest_fm.debt_to_equity
    if de is None:
        lines.append(ScoreLine("D/E < 0.5", 0.0, 2.0, "D/E n/a"))
    else:
        lines.append(ScoreLine("D/E < 0.5",
                               2.0 if de < 0.5 else (1.0 if de < 1.0 else 0.0),
                               2.0, f"D/E={num(de)}"))

    cr = latest_fm.current_ratio
    lines.append(ScoreLine(
        "Current ratio > 1.5",
        1.0 if (cr is not None and cr > 1.5) else 0.0,
        1.0,
        f"current_ratio={num(cr)}" if cr is not None else "current ratio n/a",
    ))

    fcf_series = list(line_item_series(list(line_items), "free_cash_flow"))
    if not fcf_series and latest_fm.free_cash_flow is not None:
        fcf_value = latest_fm.free_cash_flow
        detail = f"FCF={money(fcf_value)} (from metrics)"
    elif fcf_series:
        fcf_value = fcf_series[0].value
        detail = f"FCF={money(fcf_value)}"
    else:
        fcf_value = None
        detail = "FCF n/a"
    lines.append(ScoreLine(
        "FCF positive",
        1.0 if (fcf_value is not None and fcf_value > 0) else 0.0,
        1.0,
        detail,
    ))
    return lines


def _earnings_quality(metrics: list[FinancialMetrics]) -> list[ScoreLine]:
    if not metrics:
        return [ScoreLine("Earnings quality", 0.0, 3.0, "no historical metrics available")]
    by_year = sorted(metrics, key=lambda f: f.period_end, reverse=True)
    nis = [f.net_income for f in by_year if f.net_income is not None]

    lines: list[ScoreLine] = []
    positives = sum(1 for v in nis if v > 0)
    lines.append(ScoreLine(
        "Net income positive (5y)",
        2.0 if positives >= 5 else (1.0 if positives >= 3 else 0.0),
        2.0,
        f"{positives}/{len(nis)} positive years" if nis else "no NI history",
    ))

    growth_ok = sum(1 for f in by_year if (f.earnings_growth_yoy or 0) > 0)
    lines.append(ScoreLine(
        "Earnings growth YoY",
        1.0 if growth_ok >= max(2, len(by_year) // 2) else 0.0,
        1.0,
        f"{growth_ok}/{len(by_year)} years with positive YoY growth",
    ))
    return lines


def _pricing_power(metrics: list[FinancialMetrics]) -> list[ScoreLine]:
    """Gross margin level + stability — Buffett's upstream pricing-power test.

    Level is the more important of the two: a sustained high gross margin
    is direct evidence the firm prices above commodity cost. Stability
    over 3+ years rules out a one-off spike from input cost.
    """
    if not metrics:
        return [ScoreLine("Pricing power", 0.0, 2.0, "no metrics")]
    latest_fm = metrics[0] if metrics else None
    gm = latest_fm.gross_margin if latest_fm else None
    lines: list[ScoreLine] = []
    lines.append(ScoreLine(
        "Gross margin > 40%",
        1.0 if (gm is not None and gm > 0.40) else 0.0,
        1.0,
        f"gross_margin={pct(gm)}" if gm is not None else "gross margin n/a",
    ))
    gms = [f.gross_margin for f in metrics if f.gross_margin is not None]
    if len(gms) >= 3:
        sd = pstdev(gms)
        lines.append(ScoreLine(
            "Gross margin stable (σ < 5pp)",
            1.0 if sd < 0.05 else 0.0,
            1.0,
            f"σ(gross_margin)={pct(sd)} over {len(gms)} years",
        ))
    else:
        lines.append(ScoreLine("Gross margin stable", 0.0, 1.0,
                                f"<3 GM points ({len(gms)} available)"))
    return lines


def _compounding(metrics: list[FinancialMetrics]) -> tuple[list[ScoreLine], float | None]:
    """BVPS compounding rate — Buffett's "annual percentage change in book value".

    CAGR over the longest contiguous span we have. Needs both endpoints
    positive and > 1 year apart; otherwise marked unverified.
    Returns (lines, cagr_value).
    """
    bvps_series = [
        (f.period_end, f.book_value_per_share)
        for f in metrics
        if f.book_value_per_share is not None and f.book_value_per_share > 0
    ]
    if len(bvps_series) < 2:
        return ([ScoreLine("BVPS compounding", 0.0, 2.0,
                           f"need ≥2 positive BVPS; have {len(bvps_series)}")], None)
    bvps_series.sort(key=lambda t: t[0])
    start_date, start_bvps = bvps_series[0]
    end_date, end_bvps = bvps_series[-1]
    years = (end_date - start_date).days / 365.25
    if years < 1.0:
        return ([ScoreLine("BVPS compounding", 0.0, 2.0,
                           f"history span only {years:.1f}y")], None)
    cagr = (end_bvps / start_bvps) ** (1 / years) - 1
    if cagr > 0.10:
        score = 2.0
    elif cagr > 0.05:
        score = 1.0
    else:
        score = 0.0
    return ([ScoreLine(
        "BVPS CAGR > 10%",
        score, 2.0,
        f"BVPS {num(start_bvps)} → {num(end_bvps)} over {years:.1f}y → CAGR={pct(cagr)}",
    )], cagr)


def _moat(metrics: list[FinancialMetrics]) -> list[ScoreLine]:
    if not metrics or len(metrics) < 3:
        return [ScoreLine("Moat (ROE/margin stability)", 0.0, 3.0,
                          "need ≥3 years of history; only have "
                          f"{len(metrics) if metrics else 0}")]
    roes = [f.return_on_equity for f in metrics if f.return_on_equity is not None]
    op_margins = [f.operating_margin for f in metrics if f.operating_margin is not None]

    lines: list[ScoreLine] = []
    if len(roes) >= 3:
        sd = pstdev(roes)
        lines.append(ScoreLine(
            "ROE stable (std dev < 5pp)",
            2.0 if sd < 0.05 else (1.0 if sd < 0.10 else 0.0),
            2.0,
            f"σ(ROE)={pct(sd)} over {len(roes)} years",
        ))
    else:
        lines.append(ScoreLine("ROE stable", 0.0, 2.0, "<3 ROE points"))

    if len(op_margins) >= 3:
        sd = pstdev(op_margins)
        lines.append(ScoreLine(
            "Op margin stable (σ < 3pp)",
            1.0 if sd < 0.03 else 0.0,
            1.0,
            f"σ(op_margin)={pct(sd)} over {len(op_margins)} years",
        ))
    else:
        lines.append(ScoreLine("Op margin stable", 0.0, 1.0, "<3 op-margin points"))
    return lines


def _management(line_items: Iterable[LineItem],
                insider_trades: list[InsiderTrade]) -> list[ScoreLine]:
    lines: list[ScoreLine] = []

    shares = list(line_item_series(list(line_items), "shares_outstanding"))
    if len(shares) >= 2 and shares[0].value is not None and shares[-1].value is not None:
        delta = shares[0].value - shares[-1].value
        lines.append(ScoreLine(
            "Net buybacks (shares decreasing)",
            1.0 if delta < 0 else 0.0,
            1.0,
            f"shares {money(shares[-1].value)} → {money(shares[0].value)} ({'↓' if delta < 0 else '↑'})",
        ))
    else:
        lines.append(ScoreLine("Net buybacks", 0.0, 1.0, "shares-outstanding history unavailable"))

    if not insider_trades:
        lines.append(ScoreLine("Insider net buying", 0.0, 1.0,
                               "no insider data (yfinance empty for .TW or TW MOPS not yet fetched)"))
    else:
        buy_shares = sum(t.shares or 0 for t in insider_trades if t.transaction_type == "buy")
        # planned_sell already carries a negative `shares` value (sell convention).
        sell_shares = sum(abs(t.shares or 0) for t in insider_trades
                          if t.transaction_type in ("sell", "planned_sell"))
        net = buy_shares - sell_shares
        sources = {t.source for t in insider_trades}
        is_tw_synth = "twse_openapi" in sources
        planned = sum(1 for t in insider_trades if t.transaction_type == "planned_sell")
        detail_parts = [f"net Δ={money(net)} shares across {len(insider_trades)} rows"]
        if planned:
            detail_parts.append(f"includes {planned} planned-sell filing(s)")
        if is_tw_synth:
            detail_parts.append(
                "TW data is cumulative since-election snapshot — treat as stock, not recent flow"
            )
        lines.append(ScoreLine(
            "Insider net buying",
            1.0 if net > 0 else 0.0,
            1.0,
            "; ".join(detail_parts),
        ))
    return lines


def _valuation(latest_fm: FinancialMetrics | None,
                line_items: Iterable[LineItem],
                market_cap: float | None) -> tuple[list[ScoreLine], float | None, float | None, float | None]:
    """Return (lines, intrinsic_value, owner_earnings_yield, margin_of_safety).

    intrinsic = owner_earnings × 10 (10x multiple ≈ 10% required return on
    owner earnings) — conservative DCF stand-in faithful to Buffett's
    typical ballpark for stable franchises.
    """
    owner_earnings, derivation = compute_owner_earnings(latest_fm, line_items)

    if owner_earnings is None or market_cap is None or market_cap == 0:
        return (
            [ScoreLine("Owner earnings yield > 6%", 0.0, 2.0,
                       f"{derivation}; market_cap={money(market_cap)}")],
            None, None, None,
        )

    oe_yield = owner_earnings / market_cap
    intrinsic = owner_earnings * 10  # 10x ≈ 10% required return on owner earnings
    mos = (intrinsic - market_cap) / intrinsic if intrinsic > 0 else None

    score = 2.0 if oe_yield > 0.06 else (1.0 if oe_yield > 0.04 else 0.0)
    line = ScoreLine(
        "Owner earnings yield > 6%",
        score,
        2.0,
        f"OE yield={pct(oe_yield)}; intrinsic≈{money(intrinsic)}; MoS={pct(mos)}",
    )
    return [line], intrinsic, oe_yield, mos


# ---------------------------------------------------------------------------
# Entry points used by warren_buffett.py
# ---------------------------------------------------------------------------


def score(state) -> BuffettScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    insider_trades: list[InsiderTrade] = state.get("shared_data:insider_trades") or []
    market_cap = state.get("shared_data:market_cap")

    latest_fm = latest(metrics)
    val_lines, intrinsic, oe_yield, mos = _valuation(latest_fm, line_items, market_cap)
    sorted_metrics = sorted(metrics, key=lambda f: f.period_end, reverse=True) if metrics else []
    compounding_lines, bvps_cagr = _compounding(sorted_metrics)

    return BuffettScore(
        profitability=_profitability(latest_fm),
        financial_strength=_financial_strength(latest_fm, line_items),
        earnings_quality=_earnings_quality(metrics),
        pricing_power=_pricing_power(sorted_metrics),
        compounding=compounding_lines,
        moat=_moat(metrics),
        management=_management(line_items, insider_trades),
        valuation=val_lines,
        intrinsic_value=intrinsic,
        market_cap=market_cap,
        margin_of_safety=mos,
        owner_earnings_yield=oe_yield,
        bvps_cagr=bvps_cagr,
    )


def format_block(score_obj: BuffettScore) -> str:
    """Render the Buffett scorecard as a markdown block for prompt injection."""
    sections = [
        format_scorecard("Profitability", score_obj.profitability),
        format_scorecard("Financial Strength", score_obj.financial_strength),
        format_scorecard("Earnings Quality (5y)", score_obj.earnings_quality),
        format_scorecard("Pricing Power (gross margin)", score_obj.pricing_power),
        format_scorecard("Compounding (BVPS CAGR)", score_obj.compounding),
        format_scorecard("Moat Proxy (ROE/margin stability)", score_obj.moat),
        format_scorecard("Management / Capital Allocation", score_obj.management),
        format_scorecard("Valuation (Owner Earnings)", score_obj.valuation),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {score_obj.total:.1f} / {score_obj.total_max:.1f}\n"
        f"  intrinsic_value: {money(score_obj.intrinsic_value)}\n"
        f"  market_cap: {money(score_obj.market_cap)}\n"
        f"  margin_of_safety: {pct(score_obj.margin_of_safety)}\n"
        f"  owner_earnings_yield: {pct(score_obj.owner_earnings_yield)}\n"
        f"  bvps_cagr: {pct(score_obj.bvps_cagr)}"
    )
    return (
        "【Buffett 量化 checklist — 由 deterministic 規則計算，請以此為敘事依據】\n"
        "規則來源：profitability + financial strength + earnings quality + "
        "pricing power + compounding + moat proxy + management + valuation\n"
        "n/a 表示資料源未提供，應在敘事中標記為「未驗證」，不可主觀補值。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
