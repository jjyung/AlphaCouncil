from google.adk.agents.llm_agent import Agent

from alpha_council.utils.market_snapshot import build_snapshot_context
from alpha_council.utils.master_runtime import build_reports_context


# trader_plan 為錨點（必要）；其餘 debater 論點在第二輪才會存在（optional）
_CONTEXT_KEYS = ["trader_plan", "neutral_argument?", "conservative_argument?"]


_BASE = """你是風險辯論中的激進辯手，代表「高風險高報酬」立場。

上方【市場即時快照】已提供當前價、年化波動率、ATR、52 週區間與系統建議倉位。你的論點必須以這些**真實數字**為基礎，不得憑感覺主張重倉。

根據交易員的交易方案，從激進視角提出論點：
1. 進場時機：引用當前價格相對 52 週高低點的位置（from_52w_high_pct / from_52w_low_pct），論證為何現在是最佳進場時機
2. 倉位規模：參考 `position_guidance.suggested_max_position_pct`，**明確主張倉位應該超過**系統建議值多少（需有論據），或為何系統建議已經足夠
3. 若使用槓桿，理由與可接受的槓桿倍數
4. 反駁保守觀點：用 ATR 與年化波動率數字論證「這支股票的波動不算極端，可承受」
5. 停損設定建議：可採**比系統建議（2×ATR）寬鬆**的倍數，並說明何時應該加碼而非止損

語氣積極進取，但論點需**引用快照裡的具體數字**（如「當前價 $X、ATR $Y、年化波動 Z%」），不得純粹情緒化。

若上方已出現 neutral_argument 或 conservative_argument，代表這是第二輪辯論——需針對中立方與保守方的最新論點逐點反駁，並進一步強化己方立場。
"""


def _instruction(ctx) -> str:
    snapshot_block = build_snapshot_context(ctx.state)
    peer_block = build_reports_context(ctx.state, _CONTEXT_KEYS)
    parts: list[str] = []
    if snapshot_block:
        parts.append(snapshot_block)
    if peer_block:
        parts.append("【交易員方案 + 他方辯手論點（第二輪始具備 peer 論點）】\n\n" + peer_block)
    parts.append(_BASE)
    return "\n\n---\n\n".join(parts)


aggressive_debater = Agent(
    model="gemini-2.5-flash",
    name="aggressive_debater",
    description="激進辯手：主張最大化報酬，支持高倉位、高槓桿或積極進場的風險立場。",
    instruction=_instruction,
    output_key="aggressive_argument",
)
