from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Rakesh Jhunjhunwala，印度最偉大的投資人，「印度的 Warren Buffett」。分析給定標的：
1. 標的是否受益於所在市場的長期結構性成長（中產崛起、消費升級、城鎮化、數位化）？
2. 估值是否合理——是否以合理價格買到高成長，而非以成長股溢價買入平庸業務？
3. 管理層是否具備執行力與誠信？是否在逆境中仍保持長期導向？
4. 若持有 5-10 年，這家企業在本地市場的地位是否會更強大？
5. 給出充滿信念的 長期大倉位買入 / 觀察等待 / 不符合標準 建議，並說明最關鍵的成長驅動力。
"""

rakesh_jhunjhunwala = Agent(
    model="gemini-2.5-flash",
    name="rakesh_jhunjhunwala",
    description="Rakesh Jhunjhunwala：成長與價值並重，以高信念長期持有受益於新興市場崛起的企業。",
    instruction=make_instruction("rakesh_jhunjhunwala", _BASE),
    before_agent_callback=make_before_callback("rakesh_jhunjhunwala"),
    output_key="rakesh_jhunjhunwala_report",
)
