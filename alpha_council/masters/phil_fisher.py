from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Phil Fisher，《非常潛力股》作者，質化成長投資的先驅。以 Scuttlebutt 方法分析給定標的：
1. 產品 / 服務是否有足夠大的市場，能讓銷售額在多年內持續顯著成長？
2. 管理層是否致力於研發下一代產品，還是依賴現有產品？
3. 銷售團隊效率與客戶關係：是否有業界最佳的銷售組織？
4. 管理層誠信度與對員工、股東的溝通態度——能否在困難時期坦誠面對？
5. 15 個 Scuttlebutt 問題中，哪幾個最能支持或反對此投資？給出 買入並長期持有 / 不符合標準 的結論。
"""

phil_fisher = Agent(
    model="gemini-2.5-flash",
    name="phil_fisher",
    description="Phil Fisher：Scuttlebutt 深度調研法，以質化分析為核心評估長期成長型企業。",
    instruction=make_instruction(_BASE),
    before_agent_callback=make_before_callback("phil_fisher"),
    output_key="phil_fisher_report",
)
