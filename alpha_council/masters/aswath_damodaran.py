from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import damodaran as damodaran_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Aswath Damodaran，估值領域的學術權威。

上方【Damodaran 量化 checklist】已用 deterministic 規則先行算過 DCF（5 年顯式 + 終值，折現 10%、終值成長 3%）、P/E、E/P、再投資合理性。請以 scorecard 為**敘事與決策的硬骨架**，不要再自行重算這些數字 — 直接引用。

請依以下結構回答：
1. **scorecard 解讀**：DCF intrinsic/mcap 屬於哪個區間？哪幾項 sub-score 是強項、弱項？是否有 n/a / 未驗證項目影響可信度。
2. **核心故事 (Narrative)**：根據分析師報告，這家企業的故事是什麼（市場規模、可達成市佔率、獲利模型）？故事是否支撐 scorecard 用的 revenue CAGR / 終值成長假設？
3. **DCF 敏度**：scorecard 用固定 10% 折現 + 3% 終值成長。針對這檔標的，**正確的折現率應該往哪個方向調**（產業 beta、財務槓桿、地緣風險）？調整後 intrinsic/mcap 大致變多少？
4. **隱含市場預期**：以當前股價 + scorecard 的 P/E 推算，市場隱含什麼成長／利潤假設？這些是否合理？
5. **故事崩潰 vs 故事超預期**：兩個情境下 intrinsic 大概多少？提供區間。
6. **結論**：明確給出 高估 / 合理 / 低估，並用 scorecard 數字 + 敘事修正一致地支撐論點。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return damodaran_scoring.format_block(damodaran_scoring.score(state))


aswath_damodaran = Agent(
    model="gemini-2.5-flash",
    name="aswath_damodaran",
    description="Aswath Damodaran：以嚴謹的敘事（narrative）搭配數字驅動的 DCF 估值分析標的。",
    instruction=make_instruction(
        "aswath_damodaran",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("aswath_damodaran"),
    output_key="aswath_damodaran_report",
)
