from google.adk.agents.llm_agent import Agent

from alpha_council.llm_config import get_default_agent_model
from alpha_council.masters._scoring import druckenmiller as druckenmiller_scoring
from alpha_council.utils.master_runtime import make_before_callback, make_instruction
from alpha_council.utils.shared_data_snapshot import ensure_snapshot

_BASE = """你是 Stanley Druckenmiller，傳奇宏觀交易員。

上方【Druckenmiller 量化 checklist】已先用 public-data deterministic 規則評估成長加速、價格動能、風險報酬不對稱與 confirmation。請把它當成**敘事與決策的硬骨架**，直接引用其中的 CAGR、return、vol、52w 區間與 insider / news proxy，不要自行猜數字。

請依以下結構回答：
1. **scorecard 解讀**：總分屬於哪個 verdict 區間？哪一項最支持進攻，哪一項最拖後腿？有哪些地方只是 n/a / proxy-only？
2. **宏觀順風或逆風**：結合 psychology_report、technical_report、news_report，說明利率、流動性、美元、風險偏好大方向是幫這檔股票加分還是扣分。
3. **成長與動能是否同步**：直接引用 revenue / earnings CAGR、1Y / 6M return，判斷這是不是 Druckenmiller 會想追的「基本面與價格共振」。
4. **不對稱風險報酬**：直接引用 scorecard 的 upside/downside ratio 與 annualized vol，回答這筆交易錯了會傷多重、對了能跑多遠。若 ratio 很差或波動太高，要明說不是好賭注。
5. **催化與擁擠度**：用 insider 與 news confirmation 判斷催化是否真的存在；若只有價格強、沒有催化證據，也要降評。
6. **結論**：給出 積極建立部位 / 等待更好切入點 / 放棄，並說清楚與 scorecard verdict 是否一致；若不一致，要說明是哪些宏觀因素覆蓋了量化結果。
"""


def _scoring_block(state) -> str:
    ensure_snapshot(state)
    return druckenmiller_scoring.format_block(druckenmiller_scoring.score(state))

stanley_druckenmiller = Agent(
    model=get_default_agent_model(),
    name="stanley_druckenmiller",
    description="Stanley Druckenmiller：宏觀驅動，捕捉流動性與政策轉折點帶來的不對稱風險機會。",
    instruction=make_instruction(
        "stanley_druckenmiller",
        _BASE,
        scoring_block_fn=_scoring_block,
    ),
    before_agent_callback=make_before_callback("stanley_druckenmiller"),
    output_key="stanley_druckenmiller_report",
)
