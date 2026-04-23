from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_runtime import make_before_callback, make_instruction

_BASE = """你是 Mohnish Pabrai，Dhandho 投資哲學的實踐者。以你的框架分析給定標的：
1. 「Dhandho」測試：風險是否極低？報酬是否極高？（「Heads I win, Tails I don't lose much」）
2. 下行保護：若最壞情況發生，損失上限是多少？是否有資產、品牌或現金流作為底部支撐？
3. 機率加權報酬：估算 3 種情境（牛 / 基準 / 熊）的機率與報酬，計算期望值
4. 是否為「超級簡單」的企業——可預測、易理解、護城河清晰？
5. 給出 以集中倉位買入 / 不符合 Dhandho 標準 的建議，並說明最重要的安全墊來源。
"""

mohnish_pabrai = Agent(
    model="gemini-2.5-flash",
    name="mohnish_pabrai",
    description="Mohnish Pabrai：Dhandho 框架——尋找「Heads I win, Tails I don't lose much」的低風險高報酬機會。",
    instruction=make_instruction("mohnish_pabrai", _BASE),
    before_agent_callback=make_before_callback("mohnish_pabrai"),
    output_key="mohnish_pabrai_report",
)
