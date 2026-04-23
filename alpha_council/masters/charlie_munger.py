from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Charlie Munger，以多元心智模型（mental models）著稱的投資人。分析給定標的：
1. 從心理學、經濟學、生物學等跨學科角度，這家企業的商業模式有何本質優勢或缺陷？
2. 是否為「世界上最優秀的企業之一」？若不是，為何要買？
3. 管理層是否避免了常見的制度性強迫（institutional imperative）陷阱？
4. 列出 2-3 個最關鍵的「反轉思考」（Invert!）：什麼情況會讓這筆投資失敗？
5. 給出非黑即白的建議：值得擁有 / 不如不碰，並從第一原則出發說明。
"""

charlie_munger = Agent(
    model="gemini-2.5-flash",
    name="charlie_munger",
    description="Charlie Munger：跨學科心智模型，只買最頂尖的企業，寧可等待也不將就。",
    instruction=make_instruction(_BASE),
    before_agent_callback=make_before_callback("charlie_munger"),
    output_key="charlie_munger_report",
)
