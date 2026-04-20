from google.adk.agents.llm_agent import Agent

from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.agents.loop_agent import LoopAgent
from alpha_council.utils.dynamic_masters_panel import DynamicMastersPanel
from alpha_council.utils.conditional_pipeline import ConditionalPipeline

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
from alpha_council.intent_gate import intent_gate
from alpha_council.master_selector import master_selector_agent

# Phase 0 — 意圖偵測閘（最先執行）
# Writes analysis_intent: bool to session state.
# False → all downstream agents are no-ops via before_agent_callback.

# Phase 1 — 分析師團隊（目前啟用：news_analyst；其餘分析師保留 import，可按需加回）
analyst_team = ParallelAgent(
    name="analyst_team",
    sub_agents=[
        technical_analyst,
        news_analyst,
        psychology_analyst,
        fundamental_analyst,
        chip_analyst,
    ],
    description="分析師團隊：目前執行 news_analyst，產出 news_report。其餘分析師（技術、心理、籌碼、基本面）已 import 但尚未加入，可按需啟用。",
)

# Phase 1.5 — 大師選擇（使用者指定 3–7 位，或隨機 3 位）
# Skipped when analysis_intent=False (before_agent_callback on master_selector_agent).
# Writes selected_masters: list[str] to session state.

# Phase 2 — 13 位投資大師並行（僅執行已選中的大師）
# Each master checks analysis_intent + selected_masters via before_agent_callback.
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
    description="看多研究員與看空研究員進行辯論，最多循環 2 輪，凝聚多空論點。",
)

# Phase 4 — 研究管理人裁決
research_manager = Agent(
    model="gemini-2.5-flash",
    name="research_manager",
    description="綜合辯論結果，裁決最終研究結論，輸出投資信號與關鍵論據。",
    instruction="根據 research_debate 的多空論點，給出明確的買入 / 持有 / 賣出建議並說明理由。",
)

# Phase 4b — 交易員
trader = Agent(
    model="gemini-2.5-flash",
    name="trader",
    description="依據研究管理人的結論，擬定具體交易方案（標的、方向、倉位比例）。",
    instruction="根據研究管理人的投資信號，產出可執行的交易計畫，包含進場條件與停損設定。",
)

# Phase 5 — 風險辯論（最多 2 輪）
risk_debate = LoopAgent(
    name="risk_debate",
    sub_agents=[aggressive_debater, neutral_debater, conservative_debater],
    max_iterations=2,
    description="激進、中立、保守三位辯手對交易方案進行風險辯論，最多循環 2 輪。",
)

# Phase 6 — 投資組合管理人最終決策
portfolio_manager = Agent(
    model="gemini-2.5-flash",
    name="portfolio_manager",
    description="整合所有分析與風險辯論，做出最終投資組合決策，包含倉位大小與風險控管措施。",
    instruction="根據交易員方案與風險辯論結果，給出最終投資決策，需明確說明倉位比例、風險敞口與退出策略。",
)

# 主 Pipeline（ConditionalPipeline 取代 SequentialAgent）
# 路由規則：
#   analysis_intent=False → 只跑 intent_gate，輸出友善回覆，完全停止
#   analysis_intent=True + awaiting=False → intent_gate → analyst_team → master_selector
#   awaiting_master_choice=True → 在 master_selector 回覆選單後停止，不進入 Phase 2
#   masters selected + awaiting=False → 繼續執行 masters_panel（內含聚合）
#
# Session state keys:
#   intent_gate          → analysis_intent_raw, analysis_intent: bool
#   analyst_team         → news_report (+ future: technical_report, etc.)
#   master_selector      → selected_masters: list[str], awaiting_master_choice: bool
#   masters_panel        → {name}_report for each selected master
#                      + consolidated_masters_report
alpha_council_pipeline_agent = ConditionalPipeline(
    name="AlphaCouncilPipelineAgent",
    sub_agents=[
        intent_gate,
        analyst_team,
        master_selector_agent,
        masters_panel,
        research_debate,
        research_manager,
        trader,
        risk_debate,
        portfolio_manager,
    ],
    description=(
        "AlphaCouncil 投資分析流水線（條件路由）："
        "意圖偵測 → 分析師團隊 → 大師選擇 → 大師觀點（含聚合）。"
        "各階段依 session state 條件決定是否執行，不產生 skip 事件。"
    ),
)

root_agent = alpha_council_pipeline_agent
