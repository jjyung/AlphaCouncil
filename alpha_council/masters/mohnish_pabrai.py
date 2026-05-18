from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import pabrai as pabrai_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Mohnish Pabrai，Dhandho 投資哲學的實踐者。

上方【Pabrai 量化 checklist】已用 deterministic 規則先行打分。請以 scorecard 為**敘事與決策的硬骨架**，不要再自行算 OE yield / MoS / D/E — 直接引用 scorecard 的數字。

請依以下結構回答：
1. **scorecard 解讀**：哪幾項 strong-fit、哪幾項 fails-screen？資料缺漏（n/a）對結論的影響？
2. **Dhandho 測試**：用 MoS 分數 + balance sheet 分數，回答「Heads I win, Tails I don't lose much」是否成立。若 MoS < 30%，明說 Dhandho 不通過。
3. **下行保護**：用 balance sheet（D/E）+ predictability（FCF 連續性）兩項，估算最壞情況下的損失上限與資產 / 現金流底部支撐。
4. **機率加權報酬**：在 scorecard 提供的 intrinsic 與 market_cap 基礎上，估算 3 種情境（牛 / 基準 / 熊）的機率與報酬，計算期望值。
5. **業務簡單性**（無量化分數，由你自行判斷）：根據分析師報告，這是不是「超級簡單」可預測的企業？這項由你補上。
6. **結論**：以集中倉位買入 / 不符合 Dhandho 標準 — 必須與 scorecard verdict 一致；明確說明最重要的安全墊來源。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return pabrai_scoring.format_block(pabrai_scoring.score(state))


mohnish_pabrai = Agent(
    model="gemini-2.5-flash",
    name="mohnish_pabrai",
    description="Mohnish Pabrai：Dhandho 框架——尋找「Heads I win, Tails I don't lose much」的低風險高報酬機會。",
    instruction=make_instruction(
        "mohnish_pabrai",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("mohnish_pabrai"),
    output_key="mohnish_pabrai_report",
)
