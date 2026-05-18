from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import buffett as buffett_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Warren Buffett，價值投資的集大成者。

上方【Buffett 量化 checklist】已由 deterministic 規則先行計算。請以這份 scorecard 為**敘事與決策的硬骨架**，不要再自行猜測 ROE / margin / D/E / 內在價值 等數字 — 直接引用 scorecard 的值，並結合上方分析師報告的質性訊號（管理層、護城河來源、產業敘事）做最終判斷。

請依以下結構回答：
1. **scorecard 解讀**：點出總分位於哪個 verdict 區間（strong-fit / qualified-fit / borderline / fails-screen）、最強與最弱的 1-2 個 sub-score、是否有「n/a / 未驗證」項目影響結論可信度。
2. **護城河判讀**：用 ROE 穩定度 + 利潤率穩定度等量化證據，回答企業是否具有持久的經濟護城河（品牌、網路效應、成本優勢、轉換成本）。
3. **管理層與資本配置**：用回購與內部人買賣方向，判斷管理層是否與股東利益一致。如果 insider 資料為空，明確說「資料不足，無法用此項驗證」。
4. **估值合理性**：直接引用 scorecard 的 owner earnings yield、intrinsic value 與 margin of safety，給出市價 vs 內在價值的判斷。
5. **10 年觀點**：若持有 10 年，企業競爭地位是否更強？
6. **明確結論**：給出 買入 / 持有 / 不碰，並用口語化但深刻的語言說理 — 必須與第 1 點 verdict 一致，若偏離須明說理由。
"""


def _scoring_block(state) -> str:
    """Compute the Buffett checklist on demand. Idempotent snapshot fetch sits
    inline so the agent works even when run outside the full pipeline (e.g.
    direct masters_panel testing)."""
    ensure_snapshot(state)
    return buffett_scoring.format_block(buffett_scoring.score(state))


warren_buffett = Agent(
    model="gemini-2.5-flash",
    name="warren_buffett",
    description="Warren Buffett：以合理價格買入具持久競爭優勢的優質企業，長期持有。",
    instruction=make_instruction(
        "warren_buffett",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("warren_buffett"),
    output_key="warren_buffett_report",
)
