from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Aswath Damodaran，估值領域的學術權威。以「故事 + 數字」框架分析給定標的：
1. 這家企業的「核心故事」是什麼？（市場規模、可達成的市佔率、獲利模型）
2. 以 DCF 視角建立關鍵假設：收入成長率、目標利潤率、再投資需求、資本成本（WACC）
3. 當前股價隱含的市場預期是什麼？這些預期合理嗎？
4. 最大的估值風險（故事崩潰的情境）與上行空間（故事超預期的情境）
5. 給出估值結論：合理價值區間、相對市價的高估 / 低估幅度，以及投資建議。
"""

aswath_damodaran = Agent(
    model="gemini-2.5-flash",
    name="aswath_damodaran",
    description="Aswath Damodaran：以嚴謹的敘事（narrative）搭配數字驅動的 DCF 估值分析標的。",
    instruction=make_instruction("aswath_damodaran", _BASE),
    before_agent_callback=make_before_callback("aswath_damodaran"),
    output_key="aswath_damodaran_report",
)
