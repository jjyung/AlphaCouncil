from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import DEFAULT_ANALYST_KEYS, build_reports_context

# 注入分析師報告 + 大師聚合報告 + 多方論點（bull 永遠先跑，故為 required）
_CONTEXT_KEYS = DEFAULT_ANALYST_KEYS + ["consolidated_masters_report", "bull_argument"]

_BASE = """你是一位看空研究員，負責為辯論提出最強力的空方論點。

根據前序分析（技術面、新聞面、情緒面、基本面及各大師觀點），執行以下任務：
1. 整合所有支持「賣出 / 迴避」的核心論據（每點需引用具體數據或大師觀點）
2. 識別最關鍵的 2-3 個下行風險與可能的引爆時間框架
3. 反駁多方最強的論點——提出反證或說明為何多方過於樂觀
4. 提出下行目標價與理由（基於最有可能的悲觀情境）
5. 輸出結構化的「空方投資摘要」，語氣有說服力且論據具體。

若上方資料中已出現 bull_argument，需針對多方研究員的論點逐點反駁並強化己方論點。
"""


def _instruction(ctx) -> str:
    context_block = build_reports_context(ctx.state, _CONTEXT_KEYS)
    if context_block:
        return (
            "【前置分析資料 — 請優先閱讀以下內容再建構你的空方論點】\n\n"
            f"{context_block}\n\n"
            "---\n\n"
            f"{_BASE}"
        )
    return _BASE


bear_researcher = Agent(
    model="gemini-2.5-flash",
    name="bear_researcher",
    description="看空研究員：整合所有分析師與大師觀點，建構最有力的空方投資論點。",
    instruction=_instruction,
    output_key="bear_argument",
)
