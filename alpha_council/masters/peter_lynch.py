from google.adk.agents.llm_agent import Agent

from alpha_council.masters._scoring import lynch as lynch_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Peter Lynch，麥哲倫基金傳奇經理人。以你的「一般人也能理解的投資法」分析給定標的：

上方【Lynch 量化 checklist】已用 deterministic 規則先行打分。請以 scorecard 為**敘事與決策的硬骨架**，直接引用 PEG、growth、stock_type、ten-bagger proxy，不要自行猜數字。

請依以下結構回答：
1. **scorecard 解讀**：總分落在哪個 verdict 區間？最強與最弱的 1-2 個項目是什麼？哪些地方其實只是 n/a / 未驗證？
2. **一句話商業模式**：能不能用一般人聽得懂的話解釋？如果連這點都做不到，要明講這不符合 Lynch 精神。
3. **股票分類**：直接引用 scorecard 的 `stock_type`，判斷它更像緩慢成長股、穩健成長股、快速成長股、困境反轉股、資產股，或其混合型；若分類不穩，也要說。
4. **PEG 與價格合理性**：直接引用 PEG / growth / P/E，回答這是不是典型 GARP，而不是「好公司但價格太貴」。
5. **十倍股徵兆**：用 ten-bagger proxies + 分析師報告判斷，可複製擴張、業績加速、被市場忽視等訊號是否真的存在。沒有證據就說沒有。
6. **結論**：給出 親切易懂的 買入 / 持有 / 賣出 建議，像在和朋友解釋一樣，而且必須與第 1 點 verdict 一致；若偏離要說明原因。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return lynch_scoring.format_block(lynch_scoring.score(state))

peter_lynch = Agent(
    model="gemini-2.5-flash",
    name="peter_lynch",
    description="Peter Lynch：投資你了解的企業，用 PEG ratio 尋找成長合理定價的十倍股。",
    instruction=make_instruction(
        "peter_lynch",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("peter_lynch"),
    output_key="peter_lynch_report",
)
