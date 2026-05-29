from google.adk.agents.llm_agent import Agent

from alpha_council.llm_config import get_default_agent_model
from alpha_council.utils.master_runtime import (
    ANALYST_REPORT_HEADER,
    DEFAULT_ANALYST_KEYS,
    build_reports_context,
    make_peer_injector,
)

# system_instruction stays byte-identical across both LoopAgent rounds, AND
# uses the shared ANALYST_REPORT_HEADER so the `header + analyst reports`
# prefix is cacheable across:
#   - bull → bear within research_debate
#   - masters_panel → bull/bear (masters' first 5 reports overlap)
# bull_argument arrives via before_model_callback as a user message — see
# make_peer_injector.
_PREFIX_KEYS = DEFAULT_ANALYST_KEYS + ["consolidated_masters_report"]

_BASE = """你是一位看空研究員，負責為辯論提出最強力的空方論點。

根據前序分析（技術面、新聞面、情緒面、基本面及各大師觀點），執行以下任務：
1. 整合所有支持「賣出 / 迴避」的核心論據（每點需引用具體數據或大師觀點）
2. 識別最關鍵的 2-3 個下行風險與可能的引爆時間框架
3. 反駁多方最強的論點——提出反證或說明為何多方過於樂觀
4. 提出下行目標價與理由（基於最有可能的悲觀情境）
5. 輸出結構化的「空方投資摘要」，語氣有說服力且論據具體。

對話中會出現多方研究員的最新論點 (bull_argument)，需逐點反駁並強化己方論點。
"""


def _instruction(ctx) -> str:
    prefix_block = build_reports_context(ctx.state, _PREFIX_KEYS)
    if prefix_block:
        return (
            f"{ANALYST_REPORT_HEADER}\n\n"
            f"{prefix_block}\n\n"
            "---\n\n"
            f"{_BASE}"
        )
    return _BASE


bear_researcher = Agent(
    model=get_default_agent_model(),
    name="bear_researcher",
    description="看空研究員：整合所有分析師與大師觀點，建構最有力的空方投資論點。",
    instruction=_instruction,
    before_model_callback=make_peer_injector(
        peer_keys=["bull_argument"],
        header="↑ 以上為多方研究員最新論點，請逐點反駁並強化空方立場。",
    ),
    output_key="bear_argument",
)
