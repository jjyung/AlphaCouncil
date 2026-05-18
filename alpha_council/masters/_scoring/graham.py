"""Ben Graham — deep value, margin of safety, balance-sheet primacy.

Graham trades quality for *price*: he wants verifiable accounting strength
plus a meaningful discount, and treats the income statement only as a
sanity check. The scoring follows the screens from *The Intelligent
Investor* (chap. 14, "Defensive Investor") and *Security Analysis*.

  Earnings stability (3)  Positive EPS 5/5 (3) | 3-4/5 (1)
  Financial strength (4)  Current ratio > 2 (2) | D/E < 0.5 (2)
  Graham Number (3)       Price < GN (3) | Price < 1.2 × GN (1)
                          where GN = sqrt(22.5 × EPS × BVPS)
  NCAV / net-net (2)      NCAV > market_cap (2; rare!)
                          NCAV ≈ current_assets − total_liabilities
  Earnings power (2)      Avg EPS yield (E/P) > 6.7% (= 1/15 P/E ceiling) (2)
                            > 5% (1)
  Dividend record (2)     Continuous dividends in all years observed (2) |
                            ≥ 3/5 years (1)
                          Graham's *Defensive Investor* requires 20y of
                          uninterrupted dividends; yfinance only exposes
                          ~5y annual cashflow, so we score against the
                          window we have and let the LLM flag the gap.

Total cap 16. NCAV is almost always zero for modern large caps; we keep
the line because the LLM persona should still surface "no net-net here,
positive verdict has to lean on Graham Number".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
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
from alpha_council.providers.base import FinancialMetrics, LineItem


@dataclass(frozen=True)
class GrahamScore:
    earnings_stability: list[ScoreLine] = field(default_factory=list)
    financial_strength: list[ScoreLine] = field(default_factory=list)
    graham_number: list[ScoreLine] = field(default_factory=list)
    ncav: list[ScoreLine] = field(default_factory=list)
    earnings_power: list[ScoreLine] = field(default_factory=list)
    dividend_record: list[ScoreLine] = field(default_factory=list)
    graham_number_value: float | None = None
    price_per_share: float | None = None
    ncav_value: float | None = None
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
            self.earnings_stability,
            self.financial_strength,
            self.graham_number,
            self.ncav,
            self.earnings_power,
            self.dividend_record,
        )


def _earnings_stability(metrics: list[FinancialMetrics]) -> list[ScoreLine]:
    if not metrics:
        return [ScoreLine("Positive EPS history", 0.0, 3.0, "no metrics")]
    positives = sum(1 for f in metrics if f.earnings_per_share is not None and f.earnings_per_share > 0)
    n = len(metrics)
    score = 3.0 if positives >= 5 else (1.0 if positives >= 3 else 0.0)
    return [ScoreLine("Positive EPS (5y)", score, 3.0,
                       f"{positives}/{n} years with positive EPS")]


def _financial_strength(latest_fm: FinancialMetrics | None) -> list[ScoreLine]:
    if latest_fm is None:
        return [ScoreLine("Financial strength", 0.0, 4.0, "no metrics")]
    cr = latest_fm.current_ratio
    de = latest_fm.debt_to_equity
    lines = []
    lines.append(ScoreLine(
        "Current ratio > 2",
        2.0 if (cr is not None and cr > 2.0) else (1.0 if (cr is not None and cr > 1.5) else 0.0),
        2.0,
        f"current_ratio={num(cr)}" if cr is not None else "current ratio n/a",
    ))
    lines.append(ScoreLine(
        "D/E < 0.5",
        2.0 if (de is not None and de < 0.5) else (1.0 if (de is not None and de < 1.0) else 0.0),
        2.0,
        f"D/E={num(de)}" if de is not None else "D/E n/a",
    ))
    return lines


def _graham_number(
    latest_fm: FinancialMetrics | None,
    line_items: Iterable[LineItem],
    market_cap: float | None,
) -> tuple[list[ScoreLine], float | None, float | None]:
    """Returns (lines, graham_number, price_per_share)."""
    if latest_fm is None:
        return [ScoreLine("Price < Graham Number", 0.0, 3.0, "no metrics")], None, None
    eps = latest_fm.earnings_per_share
    bvps = latest_fm.book_value_per_share
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return ([ScoreLine("Price < Graham Number", 0.0, 3.0,
                           f"need EPS>0 and BVPS>0; EPS={num(eps)}, BVPS={num(bvps)}")],
                None, None)
    gn = sqrt(22.5 * eps * bvps)
    shares_series = line_item_series(list(line_items), "shares_outstanding")
    shares = shares_series[0].value if shares_series and shares_series[0].value else None
    price = market_cap / shares if (market_cap is not None and shares) else None
    if price is None:
        return ([ScoreLine("Price < Graham Number", 0.0, 3.0,
                           f"GN={num(gn)}; price unavailable (market_cap or shares missing)")],
                gn, None)
    if price < gn:
        score = 3.0
        verdict = "PASS"
    elif price < 1.2 * gn:
        score = 1.0
        verdict = "close (within 20%)"
    else:
        score = 0.0
        verdict = "FAIL"
    return ([ScoreLine("Price < Graham Number", score, 3.0,
                       f"GN={num(gn)}, price≈{num(price)} ({verdict})")],
            gn, price)


def _ncav(line_items: Iterable[LineItem],
          market_cap: float | None) -> tuple[list[ScoreLine], float | None]:
    """NCAV ≈ current_assets − total_liabilities.
    total_liabilities ≈ total_assets − total_equity (since we don't pull TL directly).
    """
    items = list(line_items)
    ca_series = line_item_series(items, "current_assets")
    ta_series = line_item_series(items, "total_assets")
    te_series = line_item_series(items, "total_equity")
    if not (ca_series and ta_series and te_series):
        return ([ScoreLine("NCAV > market cap", 0.0, 2.0,
                           "balance-sheet inputs missing (CA / TA / TE)")], None)
    ca = ca_series[0].value
    ta = ta_series[0].value
    te = te_series[0].value
    if ca is None or ta is None or te is None:
        return ([ScoreLine("NCAV > market cap", 0.0, 2.0, "balance-sheet rows nan")], None)
    total_liabilities = ta - te
    ncav = ca - total_liabilities
    if market_cap is None or market_cap == 0:
        return ([ScoreLine("NCAV > market cap", 0.0, 2.0,
                           f"NCAV={money(ncav)}; market_cap n/a")], ncav)
    ratio = ncav / market_cap
    score = 2.0 if ratio > 1.0 else 0.0
    return ([ScoreLine("NCAV > market cap (net-net)", score, 2.0,
                       f"NCAV={money(ncav)} vs mcap={money(market_cap)} (ratio={pct(ratio)})")],
            ncav)


def _earnings_power(metrics: list[FinancialMetrics],
                     line_items: Iterable[LineItem],
                     market_cap: float | None) -> list[ScoreLine]:
    """Earnings yield = avg(net_income over up to 3 years) / market_cap."""
    if not metrics or market_cap is None or market_cap == 0:
        return [ScoreLine("Earnings yield > 6.7%", 0.0, 2.0,
                          "missing metrics or market_cap")]
    nis = [f.net_income for f in metrics[:3] if f.net_income is not None]
    if not nis:
        return [ScoreLine("Earnings yield > 6.7%", 0.0, 2.0, "net income history n/a")]
    avg_ni = sum(nis) / len(nis)
    ey = avg_ni / market_cap
    score = 2.0 if ey > 0.0667 else (1.0 if ey > 0.05 else 0.0)
    return [ScoreLine("Earnings yield > 6.7%", score, 2.0,
                       f"avg NI({len(nis)}y)={money(avg_ni)} → E/P={pct(ey)}")]


def _dividend_record(line_items: Iterable[LineItem]) -> list[ScoreLine]:
    """Continuity of dividend payments in observable window.

    yfinance reports `dividends_paid` as a (typically negative) cashflow.
    We treat any *non-zero* row as a year-with-dividend. Graham's full
    20-year requirement isn't satisfiable with yfinance's ~5-year window;
    the prompt template surfaces this caveat for the LLM persona.
    """
    div_series = list(line_item_series(list(line_items), "dividends_paid"))
    if not div_series:
        return [ScoreLine("Continuous dividend record",
                           0.0, 2.0, "dividends_paid line item not in dataset")]
    n = len(div_series)
    paid = sum(1 for li in div_series if li.value is not None and abs(li.value) > 0)
    if paid == n and n >= 5:
        score = 2.0
        verdict = f"{paid}/{n} consecutive years (window-complete)"
    elif paid == n:
        score = 1.5
        verdict = f"{paid}/{n} years (window < 5y — Graham's 20y rule unverified)"
    elif paid >= 3:
        score = 1.0
        verdict = f"{paid}/{n} years (gaps present)"
    else:
        score = 0.0
        verdict = f"{paid}/{n} years (sparse / no record)"
    return [ScoreLine("Continuous dividend record", score, 2.0, verdict)]


def score(state) -> GrahamScore:
    metrics: list[FinancialMetrics] = state.get("shared_data:financial_metrics") or []
    line_items: list[LineItem] = state.get("shared_data:line_items") or []
    market_cap = state.get("shared_data:market_cap")

    latest_fm = latest(metrics)
    gn_lines, gn_value, price = _graham_number(latest_fm, line_items, market_cap)
    ncav_lines, ncav_value = _ncav(line_items, market_cap)

    return GrahamScore(
        earnings_stability=_earnings_stability(metrics),
        financial_strength=_financial_strength(latest_fm),
        graham_number=gn_lines,
        ncav=ncav_lines,
        earnings_power=_earnings_power(metrics, line_items, market_cap),
        dividend_record=_dividend_record(line_items),
        graham_number_value=gn_value,
        price_per_share=price,
        ncav_value=ncav_value,
        market_cap=market_cap,
    )


def format_block(s: GrahamScore) -> str:
    sections = [
        format_scorecard("Earnings Stability", s.earnings_stability),
        format_scorecard("Financial Strength", s.financial_strength),
        format_scorecard("Graham Number (price test)", s.graham_number),
        format_scorecard("NCAV / Net-Net", s.ncav),
        format_scorecard("Earnings Power", s.earnings_power),
        format_scorecard("Dividend Record", s.dividend_record),
    ]
    summary = (
        f"### Summary\n"
        f"  total: {s.total:.1f} / {s.total_max:.1f}\n"
        f"  graham_number: {num(s.graham_number_value)}\n"
        f"  price_per_share: {num(s.price_per_share)}\n"
        f"  ncav: {money(s.ncav_value)}\n"
        f"  market_cap: {money(s.market_cap)}"
    )
    return (
        "【Graham 量化 checklist — 深度價值，安全邊際，資產負債表優先】\n"
        "n/a 表示資料源未提供，請在敘事中標記為「未驗證」，不可主觀補值。\n"
        "NCAV 對現代大型股幾乎永遠是負的；net-net 失敗時請改用 Graham Number + 安全邊際當論述主軸。\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + summary
    )
