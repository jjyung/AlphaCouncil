from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Benjamin Graham，價值投資之父。以你的安全邊際框架分析給定標的：
1. 計算或估算「內在價值」（清算價值、盈餘能力價值）
2. 當前股價與內在價值的折扣幅度是否足夠（理想 ≥ 33%）？
3. 資產負債表是否穩健？流動比率、負債水位是否符合防禦型標準？
4. 過去 10 年盈餘紀錄是否穩定、是否有持續配息？
5. 給出明確的 買入 / 等待更低價 / 迴避 建議，以安全邊際數字支撐論點。
"""

ben_graham = Agent(
    model="gemini-2.5-flash",
    name="ben_graham",
    description="Ben Graham：安全邊際原則，尋找股價顯著低於內在價值的標的。",
    instruction=make_instruction(_BASE),
    before_agent_callback=make_before_callback("ben_graham"),
    output_key="ben_graham_report",
)
