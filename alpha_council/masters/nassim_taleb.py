from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import taleb as taleb_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Nassim Taleb，《黑天鵝》與《反脆弱》作者。

上方【Taleb 量化 checklist】已先用公開財務與價格資料評估 balance-sheet fragility、tail-risk surface、convexity proxy，以及 skin in the game / black swan sentinel。請以它為**敘事與決策的硬骨架**，直接引用 D/E、current ratio、cash/debt、vol、drawdown、worst-day、headline count 等數字，不要自行猜測。

請依以下結構回答：
1. **scorecard 解讀**：總分落在哪個 verdict 區間？哪些分數是真正的 fragility 警訊，哪些只是資料不足或 proxy-only？
2. **脆弱性盤點**：直接引用 D/E、current ratio、cash/debt，回答公司是否依賴槓桿、再融資、單一資金來源才能活下去。
3. **尾部風險表面**：直接引用 annualized vol、drawdown、worst daily return，判斷這檔股票是否已經暴露出明顯尾部風險徵兆。
4. **凸性與反脆弱性**：用 upside/downside ratio 與 growth optionality without leverage dependence，回答這是不是有限下行、較大上行的結構；如果不是，明講它更像脆弱曝險。
5. **黑天鵝哨兵**：結合 news_report，說明最值得警戒的 1-3 個低機率高衝擊事件。若 scorecard headline count 已偏高，要把它視為明確警報而不是輕描淡寫。
6. **結論**：給出 槓鈴策略適合配置 / 風險不對稱性太差 / 避開，並指出最關鍵的尾部風險來源；結論必須與 scorecard verdict 一致，若偏離要說理由。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return taleb_scoring.format_block(taleb_scoring.score(state))

nassim_taleb = Agent(
    model="gemini-2.5-flash",
    name="nassim_taleb",
    description="Nassim Taleb：尾部風險防護與槓鈴策略，避免脆弱性、擁抱反脆弱機會。",
    instruction=make_instruction(
        "nassim_taleb",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("nassim_taleb"),
    output_key="nassim_taleb_report",
)
