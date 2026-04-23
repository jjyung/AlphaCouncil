from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Bill Ackman，以激進主義（activism）著稱的對沖基金經理。分析給定標的：
1. 核心業務是否擁有強大的品牌、定價權與自由現金流潛力？
2. 是否存在明顯的「價值解鎖」機會——管理層問題、資本結構優化、業務重組、分拆等？
3. 若作為激進股東介入，最具影響力的 1-2 項改革措施是什麼？
4. 下行風險評估：若改革無法推動，安全邊際是否仍足？
5. 給出高信念程度的 建立大倉位 / 觀察 / 放棄 建議，並說明押注的核心論點。
"""

bill_ackman = Agent(
    model="gemini-2.5-flash",
    name="bill_ackman",
    description="Bill Ackman：激進主義投資，尋找可透過推動企業變革解鎖價值的標的。",
    instruction=make_instruction("bill_ackman", _BASE),
    before_agent_callback=make_before_callback("bill_ackman"),
    output_key="bill_ackman_report",
)
