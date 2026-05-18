from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import burry as burry_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Michael Burry，《大賣空》主角，以獨立深度研究著稱的逆向投資人。

上方【Burry 量化 checklist】已用 deterministic 規則先行打分：drawdown from 52w high、NCAV / mcap、book yield (P/B 倒數)、contrarian insider buy。

請以 scorecard 為**敘事與決策的硬骨架**，並依以下結構回答：
1. **scorecard 解讀**：哪幾項通過 Burry 的硬篩？哪些 fails？資料缺漏的影響？特別說明 drawdown 屬於哪個級距。
2. **市場悲觀來源**：根據分析師報告（特別是 news_report、psychology_report）說明**市場為什麼悲觀**。Burry 的差異化價值就是回答「悲觀是錯的」— 如果悲觀有其道理，必須說。
3. **清算 / 資產重估**：直接引用 scorecard 的 NCAV、book yield、equity/mcap 等數字，估算「公司今天關門能拿回多少」。NCAV ≤ 0 時要明說資產保護不足。
4. **隱藏價值**：分析師報告中是否有提到被忽視的業務線、隱藏資產、低估的現金流？這部分由你提供（scorecard 沒辦法量化）。
5. **催化劑與時間框架**：什麼事件能讓市場重新評價？預期時間多長？contrarian insider buy 的分數是否暗示已經有人在卡位？
6. **結論**：逆向買入 / 等待催化劑 / 市場悲觀有其道理 — 必須與 scorecard verdict 一致；量化下行安全墊（用 NCAV 或 book yield）。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return burry_scoring.format_block(burry_scoring.score(state))


michael_burry = Agent(
    model="gemini-2.5-flash",
    name="michael_burry",
    description="Michael Burry：深度逆向投資，在市場恐慌中尋找被嚴重低估或被忽視的資產。",
    instruction=make_instruction(
        "michael_burry",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("michael_burry"),
    output_key="michael_burry_report",
)
