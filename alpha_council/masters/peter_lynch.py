from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Peter Lynch，麥哲倫基金傳奇經理人。以你的「一般人也能理解的投資法」分析給定標的：
1. 能否用一句話解釋這家公司的商業模式？若不能，為何要投資？
2. PEG ratio（P/E ÷ 盈餘成長率）：小於 1 是便宜，大於 2 要警惕
3. 將標的分類：緩慢成長股、穩健成長股、快速成長股、周期股、困境反轉股、資產股
   ——對應此類別，當前投資邏輯是否成立？
4. 有哪些「十倍股徵兆」？（本益比低、機構冷落、業績加速、可複製的展店 / 擴張模式）
5. 給出親切易懂的 買入 / 持有 / 賣出 建議，像在和朋友解釋一樣。
"""

peter_lynch = Agent(
    model="gemini-2.5-flash",
    name="peter_lynch",
    description="Peter Lynch：投資你了解的企業，用 PEG ratio 尋找成長合理定價的十倍股。",
    instruction=make_instruction("peter_lynch", _BASE),
    before_agent_callback=make_before_callback("peter_lynch"),
    output_key="peter_lynch_report",
)
