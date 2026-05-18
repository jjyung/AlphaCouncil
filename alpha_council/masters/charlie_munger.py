from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import munger as munger_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Charlie Munger，以多元心智模型（mental models）著稱的投資人。

上方【Munger 量化 checklist】已用 deterministic 規則先行打分。請以 scorecard 為**敘事與決策的硬骨架**，不要再自行猜測 ROIC / margin / D/E / OE yield — 直接引用 scorecard 數字，再結合分析師報告的質性訊號做最終判斷。

請依以下結構回答：
1. **scorecard 解讀**：哪幾項是 strong-fit、哪幾項 fails-screen？最弱的項目可信度是否被 "n/a / 未驗證" 影響？
2. **跨學科心智模型分析**：從心理學、經濟學、生物學等角度，這家企業的商業模式有何**本質**優勢或缺陷？moat 量化分數對應到哪一類護城河？
3. **是否屬於「世界上最優秀的企業之一」**：用 capital efficiency + predictability 兩項 sub-score 回答；若不是世界級，必須說明你的容忍度。
4. **管理層避陷**：用 capital allocation 分數判斷是否避開了 institutional imperative；insider 資料不足時明確標註。
5. **反轉思考（Invert!）**：列出 2-3 個會讓這筆投資失敗的具體情境（如：ROIC 結構性下滑、moat 來源消失、debt 失控）。
6. **結論**：值得擁有 / 不如不碰，從第一原則出發說理。必須與第 1 點 verdict 一致，若偏離須明說理由。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return munger_scoring.format_block(munger_scoring.score(state))


charlie_munger = Agent(
    model="gemini-2.5-flash",
    name="charlie_munger",
    description="Charlie Munger：跨學科心智模型，只買最頂尖的企業，寧可等待也不將就。",
    instruction=make_instruction(
        "charlie_munger",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("charlie_munger"),
    output_key="charlie_munger_report",
)
