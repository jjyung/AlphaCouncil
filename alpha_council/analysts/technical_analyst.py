from google.adk.agents.llm_agent import Agent

technical_analyst = Agent(
    model="gemini-2.5-flash",
    name="technical_analyst",
    description="技術分析師：透過價格行為、均線、成交量與技術指標評估標的走勢。",
    instruction="""你是一位專業的技術分析師。針對給定的股票 ticker 與日期，輸出技術面分析報告，涵蓋：
1. 趨勢方向（上升 / 下降 / 盤整）與均線排列（MA5/20/60）
2. 關鍵支撐位與壓力位
3. 技術指標訊號：RSI（超買/超賣）、MACD（黃金/死亡交叉）、布林通道
4. 成交量趨勢（放量 / 縮量 / 異常量）
5. 技術面綜合評分（-10 到 +10，正值偏多，負值偏空）與簡短結論
""",
)
