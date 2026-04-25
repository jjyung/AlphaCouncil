from google.adk.agents.llm_agent import Agent

from alpha_council.utils.market_snapshot import build_snapshot_context
from alpha_council.utils.master_runtime import build_reports_context


# aggressive 永遠先跑故 required；conservative 第二輪才會存在（optional）
_CONTEXT_KEYS = ["trader_plan", "aggressive_argument", "conservative_argument?"]


_BASE = """你是風險辯論中的中立辯手，代表「風險調整後最優報酬」立場。

上方【市場即時快照】已提供當前價、年化波動率、ATR、vol_band 與系統建議倉位。你是辯論的仲裁者，**必須以系統建議倉位為基準錨點**評估其他兩方的主張。

根據交易員的交易方案，提出平衡的風險觀點：
1. 評估激進與保守辯手論點各自的合理之處與盲點（對照快照的真實數字，指出誰的論點有數據支撐、誰在憑感覺）
2. 折衷倉位建議：以 `position_guidance.suggested_max_position_pct` 為基準，說明當前市況（vol_band）下該略高於、略低於、或維持此水位
3. 分批進場策略：結合 ATR 與當前價格給出具體價位（如：首批在 $X、第二批在跌至 $X - 1×ATR 時加碼）
4. 停損與停利：以 ATR 為單位設計（系統預設 2×ATR，你可建議 1.5-3×ATR 之間的合理區間），並量化對應的停利目標
5. 切換條件：說明當 vol_band 轉為 high/very_high 時應傾向保守,轉為 low 時可傾向激進

語氣理性、客觀，以**具體數字與機率思維**為主軸。每個結論都必須能從快照的數據推導出來。

第二輪辯論時，aggressive_argument 已更新為激進方本輪最新論點，conservative_argument 為前一輪保守方論點——需逐點點評雙方最新立場，並修正你的仲裁建議。
"""


def _instruction(ctx) -> str:
    snapshot_block = build_snapshot_context(ctx.state)
    peer_block = build_reports_context(ctx.state, _CONTEXT_KEYS)
    parts: list[str] = []
    if snapshot_block:
        parts.append(snapshot_block)
    if peer_block:
        parts.append("【交易員方案 + 激進/保守辯手最新論點】\n\n" + peer_block)
    parts.append(_BASE)
    return "\n\n---\n\n".join(parts)


neutral_debater = Agent(
    model="gemini-2.5-flash",
    name="neutral_debater",
    description="中立辯手：以風險平衡為核心，尋求報酬與風險控管之間的最優折衷方案。",
    instruction=_instruction,
    output_key="neutral_argument",
)
