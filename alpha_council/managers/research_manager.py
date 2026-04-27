from google.adk.agents.llm_agent import Agent
from google.genai import types

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


_ANALYST_KEYS = [
    "news_report?",
    "technical_report?",
    "psychology_report?",
    "fundamentals_report?",
    "chip_report?",
]


def _research_manager_instruction(ctx) -> str:
    state = ctx.state
    analyst_block = build_reports_context(state, _ANALYST_KEYS)
    debate_block = build_reports_context(state, ["bull_argument", "bear_argument"])

    base = (
        "你是研究管理人，職責是綜合以上原始分析報告與多空辯論論點，做出最終裁決。\n\n"
        "【裁決要求 — 必須包含以下四個部分】\n\n"
        "1. **分析標的**：從報告中確認 ticker 與公司名稱，明確標注本次裁決對象。\n\n"
        "2. **投資信號**：買入 / 持有 / 賣出（擇一，需明確）。\n"
        "   - 避免以「兩邊都有道理」為由選擇持有；若選持有，需有強烈的具體理由。\n"
        "   - 對照原始分析師報告，驗核辯論雙方引用的數據是否與原始報告一致。\n\n"
        "3. **裁決依據**：\n"
        "   - 採納多方的核心理由（1-2 點，需引用具體數據並標注來源報告）\n"
        "   - 採納空方的核心風險提示（1-2 點，需引用具體數據並標注來源報告）\n\n"
        "4. **交易執行計畫**（Strategic Actions，供交易員參考）：\n"
        "   - 建議進場時機與條件\n"
        "   - 建議倉位規模（相對總投資組合的概略比例）\n"
        "   - 停損觸發條件\n"
        "   - 關鍵監控指標（若這些指標惡化，應重新評估持倉）\n"
    )

    sections: list[str] = []
    if analyst_block:
        sections.append("【原始分析師報告 — 裁決者用於驗核數據】\n\n" + analyst_block)
    if debate_block:
        sections.append("【多空辯論論點 — 多空雙方最終立場】\n\n" + debate_block)

    if sections:
        return "\n\n---\n\n".join(sections) + "\n\n---\n\n" + base
    return base


research_manager = Agent(
    model="gemini-2.5-flash",
    name="research_manager",
    description="綜合辯論結果，裁決最終研究結論，輸出投資信號與關鍵論據。",
    before_agent_callback=_skip_downstream,
    instruction=_research_manager_instruction,
    output_key="research_report",
)
