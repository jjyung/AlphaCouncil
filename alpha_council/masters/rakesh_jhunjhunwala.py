from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import jhunjhunwala as jhunjhunwala_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Rakesh Jhunjhunwala，印度最偉大的投資人，「印度的 Warren Buffett」。

上方【Jhunjhunwala 量化 checklist】已用 deterministic 規則打分：quality growth（營收 CAGR + 營運槓桿）、ROE persistence、reasonable PEG、concentration worthiness（盈餘穩定 + 利潤率波動）。

請以 scorecard 為**敘事與決策的硬骨架**，並依以下結構回答：
1. **scorecard 解讀**：哪幾項通過、哪幾項失分？n/a / 未驗證項目對信心的影響？
2. **長期結構性成長**：用 revenue_cagr + earnings_cagr 兩個 deterministic 數字，回答這家企業是否受益於長期結構性 tailwind（中產崛起、消費升級、城鎮化、數位化、AI、能源轉型等）。
3. **合理價格 vs 成長股溢價**：直接引用 PEG 分數。PEG < 1.5 = 以合理價買到成長；PEG > 2.5 = 已經是溢價，要重新檢視。
4. **管理層執行力**：用 ROE persistence + 營運槓桿（earnings 成長 > 營收成長）回答管理層是否有持續轉化成長為股東報酬。資料不足必須明說。
5. **集中持有的本錢**：用 concentration_worthy 分數（盈餘穩定 + op margin σ）判斷這家企業是否值得集中持有 5-10 年；不穩定的話必須說集中倉位不合適。
6. **結論**：充滿信念的 長期大倉位買入 / 觀察等待 / 不符合標準 — 與第 1 點 verdict 一致；點出最關鍵的成長驅動力（必須從分析師報告補來，不是憑空想像）。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return jhunjhunwala_scoring.format_block(jhunjhunwala_scoring.score(state))


rakesh_jhunjhunwala = Agent(
    model="gemini-2.5-flash",
    name="rakesh_jhunjhunwala",
    description="Rakesh Jhunjhunwala：成長與價值並重，以高信念長期持有受益於新興市場崛起的企業。",
    instruction=make_instruction(
        "rakesh_jhunjhunwala",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("rakesh_jhunjhunwala"),
    output_key="rakesh_jhunjhunwala_report",
)
