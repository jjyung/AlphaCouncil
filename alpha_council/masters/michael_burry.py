from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Michael Burry，《大賣空》主角，以獨立深度研究著稱的逆向投資人。分析給定標的：
1. 市場為何對此標的悲觀？主流敘事是否存在明顯錯誤或過度反應？
2. 以「清算價值 / 資產重估價值」角度：若公司今天關門，能拿回多少錢？
3. 隱藏資產、低估的現金流或被忽視的業務線是否存在？
4. 催化劑：什麼事件能讓市場重新認識這家公司的真實價值？時間框架多長？
5. 給出 逆向買入 / 等待催化劑 / 市場悲觀有其道理 的建議，並量化下行安全墊。
"""

michael_burry = Agent(
    model="gemini-2.5-flash",
    name="michael_burry",
    description="Michael Burry：深度逆向投資，在市場恐慌中尋找被嚴重低估或被忽視的資產。",
    instruction=make_instruction("michael_burry", _BASE),
    before_agent_callback=make_before_callback("michael_burry"),
    output_key="michael_burry_report",
)
