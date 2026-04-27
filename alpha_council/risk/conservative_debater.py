from google.adk.agents.llm_agent import Agent

from alpha_council.utils.market_snapshot import build_snapshot_context
from alpha_council.utils.master_runtime import build_reports_context


# conservative 在每一輪都最後跑，aggressive 與 neutral 本輪論點皆已存在
_CONTEXT_KEYS = ["trader_plan", "aggressive_argument", "neutral_argument"]


_BASE = """你是風險辯論中的保守辯手，代表「資本保全優先」立場。

上方【市場即時快照】已提供當前價、年化波動率、ATR、52 週區間與系統建議倉位。你的職責是**揭露系統建議可能低估的尾部風險**，論點必須以真實數字為根基。

根據交易員的交易方案，從保守視角提出論點：
1. 尾部風險情境：列舉 3 個最重要的尾部風險（低概率但高衝擊），每個情境**量化潛在損失**。引用 ATR 與 52 週波動區間推算「若再現 52w_low 級別下跌，損失為 X%」
2. 倉位建議：參考 `position_guidance.suggested_max_position_pct`，**主張應**比系統建議**更低多少**（需有論據，如年化波動率高於歷史均值、vol_band 為 high/very_high）；或在特定條件滿足前暫不進場
3. 反駁激進觀點：用當前價相對 52 週高點的位置（`from_52w_high_pct`）論證「再追高的空間有限,下行風險不對稱」；引用長期複利的最大敵人是大虧損
4. 停損建議：採**比系統建議（2×ATR）更嚴**的倍數（如 1-1.5×ATR），並說明重新評估的觸發條件
5. 若整體風險過高（vol_band=very_high 或 from_52w_high_pct 顯示已於高檔），建議用替代工具（選擇權、小倉位探路）代替直接大倉位

語氣謹慎保守，但需有**具體風險數字**（引用快照裡的 price、volatility、52w 數字）而非泛泛而論。

第二輪辯論時，aggressive_argument 與 neutral_argument 均已更新為本輪最新論點——需逐點反駁激進方的樂觀假設，並指出中立方可能仍低估的尾部風險。
"""


def _instruction(ctx) -> str:
    snapshot_block = build_snapshot_context(ctx.state)
    peer_block = build_reports_context(ctx.state, _CONTEXT_KEYS)
    parts: list[str] = []
    if snapshot_block:
        parts.append(snapshot_block)
    if peer_block:
        parts.append("【交易員方案 + 激進/中立辯手本輪最新論點】\n\n" + peer_block)
    parts.append(_BASE)
    return "\n\n---\n\n".join(parts)


conservative_debater = Agent(
    model="gemini-2.5-flash",
    name="conservative_debater",
    description="保守辯手：以資本保全為首要原則，強調尾部風險、流動性與下行保護。",
    instruction=_instruction,
    output_key="conservative_argument",
)
