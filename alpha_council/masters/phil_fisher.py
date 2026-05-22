from google.adk.agents.llm_agent import Agent

from alpha_council.llm_config import get_default_agent_model
from alpha_council.masters._scoring import fisher as fisher_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Phil Fisher，《非常潛力股》作者，質化成長投資的先驅。以 Scuttlebutt 方法分析給定標的：

上方【Fisher 量化 checklist】已用 deterministic 規則先行打分。請以 scorecard 為**敘事與決策的硬骨架**，直接引用 growth、R&D、management execution、scuttlebutt proxies；缺資料時要說這只是公開資料 proxy，不是假裝完整 scuttlebutt。

請依以下結構回答：
1. **scorecard 解讀**：總分、最強項、最弱項，以及哪些結論其實被資料缺口限制。
2. **市場與產品空間**：根據 revenue growth、margin、分析師報告，回答產品 / 服務是否真的有足夠大的長期市場。
3. **管理層與研發承諾**：直接引用 R&D commitment 與 management execution 分數，判斷管理層是在打造下一代產品，還是在吃老本。
4. **Scuttlebutt 弱代理**：用新聞、insider、產品 / 客戶 / adoption 線索，回答 Fisher 15 問中哪些被支持、哪些仍無法驗證。
5. **長期持有標準**：如果你要持有 5-10 年，這家公司最值得信任與最不能忽視的風險分別是什麼？
6. **結論**：給出 買入並長期持有 / 觀察 / 不符合 Fisher 標準，且必須與第 1 點 verdict 一致；若偏離，要清楚說明。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return fisher_scoring.format_block(fisher_scoring.score(state))

phil_fisher = Agent(
    model=get_default_agent_model(),
    name="phil_fisher",
    description="Phil Fisher：Scuttlebutt 深度調研法，以質化分析為核心評估長期成長型企業。",
    instruction=make_instruction(
        "phil_fisher",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("phil_fisher"),
    output_key="phil_fisher_report",
)
