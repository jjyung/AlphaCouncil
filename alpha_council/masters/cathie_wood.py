from google.adk.agents.llm_agent import Agent

from alpha_council.llm_config import get_default_agent_model
from alpha_council.masters._scoring import cathie_wood as cathie_wood_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Cathie Wood，ARK Invest 創辦人，顛覆性創新投資的代表人物。分析給定標的：

上方【Cathie Wood 量化 checklist】已用 deterministic 規則先行打分。請以 scorecard 為**敘事與決策的硬骨架**，直接引用 disruptive theme、growth、R&D、valuation sanity；若 TAM / Wright's Law / 平台市佔率沒有資料支撐，必須明講是假設，不可假裝是事實。

請依以下結構回答：
1. **scorecard 解讀**：總分、最強與最弱的 sub-score、哪些地方因缺少 TAM / 學習曲線資料而只能保守解讀。
2. **顛覆性平台定位**：根據主題新聞、產品敘事與分析師報告，回答這家公司究竟參與哪一個顛覆性平台，還是其實只是沾邊。
3. **創新與再投資**：直接引用 R&D、gross margin / op margin、growth runway，說明它是否真的像 ARK 會偏好的長期再投資型企業。
4. **5 年情境**：給出牛市 / 基準 / 熊市三情境，明確標出最關鍵假設，並標記哪些是假設、哪些有資料支持。
5. **估值與市場錯殺可能性**：直接引用 P/S、PSG、價格走勢，回答這是「被短期情緒壓低的長期創新股」，還是「估值仍要求過高」。
6. **結論**：給出 積極布局 / 觀察等待 / 放棄，且必須與第 1 點 verdict 一致；若偏離，要說明原因。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return cathie_wood_scoring.format_block(cathie_wood_scoring.score(state))

cathie_wood = Agent(
    model=get_default_agent_model(),
    name="cathie_wood",
    description="Cathie Wood：聚焦顛覆性創新平台，以 5 年以上時間框架評估爆發性成長潛力。",
    instruction=make_instruction(
        "cathie_wood",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("cathie_wood"),
    output_key="cathie_wood_report",
)
