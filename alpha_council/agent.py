from google.adk.agents.llm_agent import Agent
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.genai import types

from alpha_council.utils.master_runtime import DynamicMastersPanel, build_reports_context
from alpha_council.utils.market_snapshot import build_snapshot_context

from alpha_council.analysts import (
    technical_analyst,
    news_analyst,
    psychology_analyst,
    fundamental_analyst,
    chip_analyst,
)
from alpha_council.masters import (
    warren_buffett,
    ben_graham,
    charlie_munger,
    aswath_damodaran,
    bill_ackman,
    cathie_wood,
    michael_burry,
    peter_lynch,
    phil_fisher,
    mohnish_pabrai,
    stanley_druckenmiller,
    rakesh_jhunjhunwala,
    nassim_taleb,
)
from alpha_council.researchers import bull_researcher, bear_researcher
from alpha_council.risk import aggressive_debater, neutral_debater, conservative_debater
from alpha_council.trader import trader
from alpha_council.managers import research_manager
from alpha_council.master_selector import master_selector_agent
from guardrail.stock_code_guard import stock_code_guard_callback


# ---------------------------------------------------------------------------
# Pipeline-specific guard callbacks
# ---------------------------------------------------------------------------


def _skip_analyst_team(callback_context) -> types.Content | None:
    """Skip analyst_team when analysis_intent=False (chitchat) or awaiting master choice."""
    state = callback_context.state
    if state.get("analysis_intent") is False:
        return types.Content(parts=[])
    if state.get("awaiting_master_choice"):
        return types.Content(parts=[])
    return None


def _skip_downstream(callback_context) -> types.Content | None:
    """Skip downstream phases when awaiting master choice or no consolidated report yet."""
    state = callback_context.state
    if state.get("analysis_intent") is False:
        return types.Content(parts=[])
    if state.get("awaiting_master_choice"):
        return types.Content(parts=[])
    if not state.get("consolidated_masters_report"):
        return types.Content(parts=[])
    return None

# Phase 1 — 分析師團隊
# Skipped when analysis_intent=False (chitchat) or awaiting_master_choice=True (round 2).
analyst_team = ParallelAgent(
    name="analyst_team",
    sub_agents=[
        technical_analyst,
        news_analyst,
        psychology_analyst,
        fundamental_analyst,
        chip_analyst,
    ],
    before_agent_callback=_skip_analyst_team,
    description="並行執行技術、新聞、市場心理、籌碼面與基本面五位分析師，產出各自的分析報告。",
)

# Phase 1.5 — 大師選擇（使用者指定 3–7 位，或隨機 3 位）
# before_agent_callback=skip_if_no_analysis_intent already on master_selector_agent.
# Writes selected_masters: list[str] and awaiting_master_choice: bool to session state.

# Phase 2 — 13 位投資大師（僅執行已選中的大師）
# Skip logic handled inside DynamicMastersPanel._run_async_impl:
#   analysis_intent=False → skip; awaiting_master_choice=True → skip; selected empty → skip.
masters_panel = DynamicMastersPanel(
    name="masters_panel",
    sub_agents=[
        warren_buffett,
        ben_graham,
        charlie_munger,
        aswath_damodaran,
        bill_ackman,
        cathie_wood,
        michael_burry,
        peter_lynch,
        phil_fisher,
        mohnish_pabrai,
        stanley_druckenmiller,
        rakesh_jhunjhunwala,
        nassim_taleb,
    ],
    description="動態大師面板：只執行 state['selected_masters'] 中的大師，不產生未選中的 no-op 事件。",
)

# Phase 3 — 看多 / 看空研究員辯論（最多 2 輪）
research_debate = LoopAgent(
    name="research_debate",
    sub_agents=[bull_researcher, bear_researcher],
    max_iterations=2,
    before_agent_callback=_skip_downstream,
    description="看多研究員與看空研究員進行辯論，最多循環 2 輪，凝聚多空論點。",
)

# Phase 4 — 研究管理人裁決 → alpha_council.managers.research_manager
# Phase 4b — 交易員 → alpha_council.trader.trader

# Phase 5 — 風險辯論（最多 2 輪）
risk_debate = LoopAgent(
    name="risk_debate",
    sub_agents=[aggressive_debater, neutral_debater, conservative_debater],
    max_iterations=2,
    before_agent_callback=_skip_downstream,
    description="激進、中立、保守三位辯手對交易方案進行風險辯論，最多循環 2 輪。",
)

# Phase 6 — 投資組合管理人最終決策
def _portfolio_manager_instruction(ctx) -> str:
    snapshot_block = build_snapshot_context(ctx.state)
    upstream_block = build_reports_context(ctx.state, ["research_report?", "trader_plan?"])
    risk_block = build_reports_context(
        ctx.state,
        ["aggressive_argument?", "neutral_argument?", "conservative_argument?"],
    )
    base = (
        "你是投資組合管理人，負責做出最終投資決策。\n\n"
        "上方已提供【市場即時快照】、研究管理人裁決、交易員執行計畫與風險辯論三方最終論點。"
        "綜合所有資訊，輸出以下結構：\n"
        "1. **最終決策**：買入 / 持有 / 賣出（需與研究信號一致或說明偏差理由）\n"
        "2. **建議倉位比例**：以 `position_guidance.suggested_max_position_pct` 為錨點；"
        "明確說明綜合風險辯論三方意見後是否調整，並量化差異（如：激進方主張 30%、保守方主張 10%、系統建議 20%，最終採 X% 並說明加權邏輯）\n"
        "3. **風險敞口控管**：\n"
        "   - 停損設定：引用或調整 `position_guidance.stop_loss.suggested_stop_price`，並參考保守方是否建議更嚴格倍數\n"
        "   - 最大可接受損失：以「倉位 % × 停損損失幅度」估算組合層級風險敞口\n"
        "4. **退出策略**：目標價以 ATR 倍數表達（如「進場價 + 3×ATR」），並列出提前出場觸發條件（如 vol_band 升級、基本面惡化）\n"
        "5. **辯論採納說明**：明確指出最終決策採納了激進、中立、保守三方中哪些具體觀點、"
        "駁回了哪些、為何。不得對三方論點視而不見。\n"
    )
    parts: list[str] = []
    if snapshot_block:
        parts.append(snapshot_block)
    if upstream_block:
        parts.append(f"【研究管理人裁決與交易員計畫】\n\n{upstream_block}")
    if risk_block:
        parts.append(f"【風險辯論三方最終論點】\n\n{risk_block}")
    parts.append(base)
    return "\n\n---\n\n".join(parts)

portfolio_manager = Agent(
    model="gemini-2.5-flash",
    name="portfolio_manager",
    description="整合所有分析、風險辯論與市場真實數據，做出最終投資組合決策，包含倉位大小與風險控管措施。",
    before_agent_callback=_skip_downstream,
    instruction=_portfolio_manager_instruction,
)

# ---------------------------------------------------------------------------
# 主 Pipeline（SequentialAgent）
# 目前啟用順序：analyst_team → master_selector → masters_panel → research_debate → research_manager → trader → risk_debate → portfolio_manager
#
# 條件跳過由各 agent 的 before_agent_callback 負責；允許 skip events。
#
# Session state keys:
#   analyst_team         → news_report, technical_report, psychology_report, fundamentals_report, chip_report
#   master_selector      → selected_masters: list[str], awaiting_master_choice: bool
#   masters_panel        → {name}_report for each selected master
#                        + consolidated_masters_report
#   bull_researcher      → bull_argument  (每輪覆寫，第二輪已含對 bear 的回應)
#   bear_researcher      → bear_argument  (每輪覆寫，第二輪已含對 bull 的回應)
#   research_manager     → research_report
#   trader               → trader_plan

alpha_council_pipeline_agent = SequentialAgent(
    name="AlphaCouncilPipelineAgent",
    sub_agents=[
        analyst_team,
        master_selector_agent,
        masters_panel,
        research_debate,
        research_manager,
        trader,
        risk_debate,
        portfolio_manager,
    ],
    before_agent_callback=stock_code_guard_callback,
    description=(
        "AlphaCouncil 投資分析流水線（SequentialAgent）："
        "股票代號格式檢查 → 分析師團隊 → 大師選擇 → 大師觀點（含聚合）→ 研究辯論 → 研究裁決 → 交易員 → 風險辯論 → 投資組合管理人。"
        "各階段透過 before_agent_callback 條件跳過，允許 skip events。"
    ),
)

root_agent = alpha_council_pipeline_agent
