from datetime import date, datetime

from alpha_council.masters._scoring import druckenmiller as druckenmiller_scoring
from alpha_council.masters._scoring import taleb as taleb_scoring
from alpha_council.masters.nassim_taleb import nassim_taleb
from alpha_council.masters.stanley_druckenmiller import stanley_druckenmiller
from alpha_council.providers.base import CompanyNews, FinancialMetrics, InsiderTrade, LineItem, PriceBar


class DummyCtx:
    def __init__(self, state: dict):
        self.state = state


def _sample_state() -> dict:
    metrics = [
        FinancialMetrics(
            ticker="NVDA",
            period_end=date(2021, 12, 31),
            period="annual",
            revenue=16_700_000_000,
            net_income=4_300_000_000,
            debt_to_equity=0.45,
            current_ratio=2.1,
            revenue_growth_yoy=0.22,
        ),
        FinancialMetrics(
            ticker="NVDA",
            period_end=date(2022, 12, 31),
            period="annual",
            revenue=26_900_000_000,
            net_income=9_800_000_000,
            debt_to_equity=0.40,
            current_ratio=2.2,
            revenue_growth_yoy=0.28,
        ),
        FinancialMetrics(
            ticker="NVDA",
            period_end=date(2023, 12, 31),
            period="annual",
            revenue=60_900_000_000,
            net_income=29_800_000_000,
            debt_to_equity=0.35,
            current_ratio=2.7,
            revenue_growth_yoy=0.33,
        ),
    ]
    line_items = [
        LineItem("NVDA", date(2023, 12, 31), "annual", "total_debt", 12_000_000_000),
        LineItem("NVDA", date(2023, 12, 31), "annual", "cash_and_equivalents", 26_000_000_000),
        LineItem("NVDA", date(2023, 12, 31), "annual", "total_equity", 34_000_000_000),
    ]
    insider = [
        InsiderTrade(
            ticker="NVDA",
            transaction_date=date(2026, 1, 3),
            insider_name="Founder",
            title="CEO",
            transaction_type="buy",
            shares=50_000,
            price=140.0,
            value=7_000_000,
        )
    ]
    news = [
        CompanyNews(
            ticker="NVDA",
            published_at=datetime(2026, 1, 10, 8, 0, 0),
            title="AI platform adoption expands across enterprise customers",
            summary="New product rollout and customer demand support further expansion.",
        ),
        CompanyNews(
            ticker="NVDA",
            published_at=datetime(2026, 1, 15, 8, 0, 0),
            title="Robotics launch and partnership deepen platform growth",
            summary="Management highlights backlog, developer adoption and partnerships.",
        ),
    ]
    prices = [
        PriceBar("NVDA", date(2025, 1, 2), 100.0, 102.0, 98.0, 100.0),
        PriceBar("NVDA", date(2025, 3, 31), 110.0, 112.0, 108.0, 110.0),
        PriceBar("NVDA", date(2025, 6, 30), 118.0, 121.0, 116.0, 120.0),
        PriceBar("NVDA", date(2025, 9, 30), 132.0, 135.0, 129.0, 133.0),
        PriceBar("NVDA", date(2025, 11, 30), 144.0, 148.0, 141.0, 146.0),
        PriceBar("NVDA", date(2025, 12, 31), 151.0, 156.0, 149.0, 155.0),
    ]
    return {
        "shared_data:financial_metrics": metrics,
        "shared_data:line_items": line_items,
        "shared_data:company_news": news,
        "shared_data:insider_trades": insider,
        "shared_data:prices": prices,
        "shared_data:market_cap": 1_150_000_000_000,
        "shared_data:fetched_at": "2026-01-20T00:00:00+00:00",
    }


def test_druckenmiller_scoring_smoke() -> None:
    score = druckenmiller_scoring.score(_sample_state())

    assert score.total > 0
    assert score.one_year_return is not None
    assert "Druckenmiller 量化 checklist" in druckenmiller_scoring.format_block(score)


def test_taleb_scoring_smoke() -> None:
    score = taleb_scoring.score(_sample_state())

    assert score.total > 0
    assert score.annualized_vol is not None
    assert "Taleb 量化 checklist" in taleb_scoring.format_block(score)


def test_risk_scores_handle_missing_data() -> None:
    empty_state = {"shared_data:fetched_at": "2026-01-20T00:00:00+00:00"}

    assert druckenmiller_scoring.score(empty_state).total == 0
    assert taleb_scoring.score(empty_state).total == 0


def test_risk_master_instruction_includes_scorecard() -> None:
    state = _sample_state()

    druck_prompt = stanley_druckenmiller.instruction(DummyCtx(state))
    taleb_prompt = nassim_taleb.instruction(DummyCtx(state))

    assert "【Druckenmiller 量化 checklist" in druck_prompt
    assert "【Taleb 量化 checklist" in taleb_prompt
