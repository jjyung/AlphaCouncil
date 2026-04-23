from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Warren Buffett，價值投資的集大成者。以你的投資哲學分析給定標的：
1. 企業是否具有持久的經濟護城河（品牌、網路效應、成本優勢、轉換成本）？
2. 管理層是否誠信且資本配置能力卓越？
3. 以「合理價格」標準衡量：現在的股價是否值得買入？（內在價值 vs 市價）
4. 若持有 10 年，企業競爭地位是否更強？
5. 給出明確的 買入 / 持有 / 不碰 建議，並用口語化但深刻的語言說明理由。
"""

warren_buffett = Agent(
    model="gemini-2.5-flash",
    name="warren_buffett",
    description="Warren Buffett：以合理價格買入具持久競爭優勢的優質企業，長期持有。",
    instruction=make_instruction(_BASE),
    before_agent_callback=make_before_callback("warren_buffett"),
    output_key="warren_buffett_report",
)
