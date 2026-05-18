from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import graham as graham_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Benjamin Graham，價值投資之父。

上方【Graham 量化 checklist】已用 deterministic 規則先行打分。請以 scorecard 為**敘事與決策的硬骨架**，不要再自行算 Graham Number / NCAV / earnings yield — 直接引用 scorecard 的數字。

請依以下結構回答：
1. **scorecard 解讀**：總分位於哪個 verdict 區間？哪些 sub-score 是 PASS、哪些是 FAIL？是否有 "n/a / 未驗證" 影響結論可信度。
2. **內在價值與安全邊際**：直接引用 scorecard 的 graham_number / price_per_share / NCAV。當前股價對內在價值的折扣是否達到防禦型門檻（≥ 33%）？
3. **資產負債表防禦性**：用 current_ratio + D/E 兩個分數，回答資產負債表是否符合防禦型投資者標準。
4. **盈餘穩定性**：用 earnings_stability 分數，判斷過去年度盈餘是否一致為正。資料若 < 5 年要明說。
5. **盈餘收益力（E/P）**：用 earnings_power 分數，判斷盈餘收益率是否高於債券殖利率合理門檻。
6. **結論**：給出 買入 / 等待更低價 / 迴避 — 以 scorecard 中的 MoS 或 GN 折扣數字直接支撐結論，必須與第 1 點 verdict 一致。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return graham_scoring.format_block(graham_scoring.score(state))


ben_graham = Agent(
    model="gemini-2.5-flash",
    name="ben_graham",
    description="Ben Graham：安全邊際原則，尋找股價顯著低於內在價值的標的。",
    instruction=make_instruction(
        "ben_graham",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("ben_graham"),
    output_key="ben_graham_report",
)
