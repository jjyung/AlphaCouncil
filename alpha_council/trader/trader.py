from google.adk.agents.llm_agent import Agent
from google.genai import types

from alpha_council.utils.market_snapshot import get_market_snapshot
from alpha_council.utils.master_runtime import build_reports_context


def _skip_downstream(callback_context) -> types.Content | None:
    state = callback_context.state
    if state.get("analysis_intent") is False:
        return types.Content(parts=[])
    if state.get("awaiting_master_choice"):
        return types.Content(parts=[])
    if not state.get("consolidated_masters_report"):
        return types.Content(parts=[])
    return None


def _trader_instruction(ctx) -> str:
    state = ctx.state
    research_block = build_reports_context(state, ["research_report?"])

    base = (
        "你是交易員，負責將研究管理人的裁決轉化為可立即執行的交易指令。\n\n"
        "【開場必做】先呼叫 `get_market_snapshot(ticker, market)` 取得當前價、ATR-14、"
        "年化波動率、52 週高低點與系統建議倉位/停損。所有價位與倉位必須以此工具回傳的"
        "**真實數字**為基礎，不得憑感覺估計。\n\n"
        "【輸出結構 — 必須依序包含以下五個部分】\n\n"
        "1. **交易標的**：確認 ticker 與公司名稱，並標注 `get_market_snapshot` 回傳的當前價格與 as_of_date。\n\n"
        "2. **交易方向**：買入 / 持有 / 賣出（需與研究管理人裁決一致，若有偏差須說明原因）。\n\n"
        "3. **執行計畫**：\n"
        "   - 建議進場價格區間（引用 current 價格 ± 某倍 ATR，例如「$X 至 $X + 0.5×ATR」）\n"
        "   - 建議倉位規模：以 `position_guidance.suggested_max_position_pct` 為基準，說明採用此值或偏離的理由（偏離須量化，如「建議採 10%，低於系統建議的 15%，因為⋯」）\n"
        "   - 分批進場策略（若適用），需標注各批次觸發價位\n\n"
        "4. **風險控管**：\n"
        "   - 停損價格：優先採用 `position_guidance.stop_loss.suggested_stop_price`（進場價 - 2×ATR），若偏離需量化說明\n"
        "   - 最大可接受損失：以「倉位 % × 停損觸發損失 %」估算絕對金額或組合百分比\n\n"
        "5. **出場策略**：\n"
        "   - 目標價或獲利了結條件（以 ATR 倍數設計，例如「進場價 + 3×ATR」）\n"
        "   - 若基本面或技術面惡化（如 vol_band 升級為 very_high），提前出場的觸發條件\n\n"
        "【格式要求】\n"
        "回應最後一行必須為：\n"
        "FINAL TRANSACTION PROPOSAL: **買入** / **持有** / **賣出**（擇一）"
    )

    if research_block:
        return (
            "【研究管理人裁決結論 — 交易指令依據】\n\n"
            f"{research_block}\n\n"
            "---\n\n"
            f"{base}"
        )
    return base


trader = Agent(
    model="gemini-2.5-flash",
    name="trader",
    description="依據研究管理人的結論，擬定具體可執行的交易指令（方向、倉位、停損、出場），並以 get_market_snapshot 的真實數字為基礎。",
    tools=[get_market_snapshot],
    before_agent_callback=_skip_downstream,
    instruction=_trader_instruction,
    output_key="trader_plan",
)
