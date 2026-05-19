from datetime import date, datetime

from alpha_council.masters._scoring import cathie_wood as cathie_scoring
from alpha_council.masters._scoring import fisher as fisher_scoring
from alpha_council.masters._scoring import lynch as lynch_scoring
from alpha_council.masters.cathie_wood import cathie_wood
from alpha_council.masters.peter_lynch import peter_lynch
from alpha_council.masters.phil_fisher import phil_fisher
from alpha_council.providers.base import CompanyNews, FinancialMetrics, LineItem, PriceBar


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
            gross_margin=0.62,
            operating_margin=0.29,
            return_on_equity=0.28,
            debt_to_equity=0.45,
            current_ratio=2.1,
        ),
        FinancialMetrics(
            ticker="NVDA",
            period_end=date(2022, 12, 31),
            period="annual",
            revenue=26_900_000_000,
            net_income=9_800_000_000,
            gross_margin=0.64,
            operating_margin=0.31,
            return_on_equity=0.31,
            debt_to_equity=0.40,
            current_ratio=2.2,
        ),
        FinancialMetrics(
            ticker="NVDA",
            period_end=date(2023, 12, 31),
            period="annual",
            revenue=60_900_000_000,
            net_income=29_800_000_000,
            gross_margin=0.73,
            operating_margin=0.45,
            return_on_equity=0.52,
            debt_to_equity=0.35,
            current_ratio=2.7,
        ),
    ]
    line_items = [
        LineItem("NVDA", date(2023, 12, 31), "annual", "shares_outstanding", 2_450_000_000),
        LineItem("NVDA", date(2022, 12, 31), "annual", "shares_outstanding", 2_440_000_000),
        LineItem("NVDA", date(2021, 12, 31), "annual", "shares_outstanding", 2_430_000_000),
        LineItem("NVDA", date(2023, 12, 31), "annual", "research_and_development", 8_700_000_000),
        LineItem("NVDA", date(2022, 12, 31), "annual", "research_and_development", 7_300_000_000),
        LineItem("NVDA", date(2021, 12, 31), "annual", "research_and_development", 5_200_000_000),
        LineItem("NVDA", date(2023, 12, 31), "annual", "total_equity", 34_000_000_000),
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
            title="Robotics and autonomous systems launch new developer platform",
            summary="Management highlights long-term platform growth and partnerships.",
        ),
    ]
    prices = [
        PriceBar("NVDA", date(2025, 1, 1), 100.0, 102.0, 98.0, 100.0),
        PriceBar("NVDA", date(2025, 12, 31), 155.0, 160.0, 150.0, 155.0),
    ]
    return {
        "shared_data:financial_metrics": metrics,
        "shared_data:line_items": line_items,
        "shared_data:company_news": news,
        "shared_data:insider_trades": [],
        "shared_data:prices": prices,
        "shared_data:market_cap": 1_150_000_000_000,
        "shared_data:fetched_at": "2026-01-20T00:00:00+00:00",
    }


def test_lynch_scoring_smoke() -> None:
    score = lynch_scoring.score(_sample_state())

    assert score.total > 0
    assert score.stock_type == "fast_grower"
    assert "Lynch 量化 checklist" in lynch_scoring.format_block(score)


def test_fisher_scoring_smoke() -> None:
    score = fisher_scoring.score(_sample_state())

    assert score.total > 0
    assert score.rd_intensity is not None
    assert "Fisher 量化 checklist" in fisher_scoring.format_block(score)


def test_cathie_scoring_smoke() -> None:
    score = cathie_scoring.score(_sample_state())

    assert score.total > 0
    assert score.psg_ratio is not None
    assert "Cathie Wood 量化 checklist" in cathie_scoring.format_block(score)


def test_growth_scores_handle_missing_data() -> None:
    empty_state = {"shared_data:fetched_at": "2026-01-20T00:00:00+00:00"}

    assert lynch_scoring.score(empty_state).total == 0
    assert fisher_scoring.score(empty_state).total == 0
    assert cathie_scoring.score(empty_state).total == 0


def test_master_instruction_includes_scorecard() -> None:
    state = _sample_state()

    lynch_prompt = peter_lynch.instruction(DummyCtx(state))
    fisher_prompt = phil_fisher.instruction(DummyCtx(state))
    cathie_prompt = cathie_wood.instruction(DummyCtx(state))

    assert "【Lynch 量化 checklist" in lynch_prompt
    assert "【Fisher 量化 checklist" in fisher_prompt
    assert "【Cathie Wood 量化 checklist" in cathie_prompt
