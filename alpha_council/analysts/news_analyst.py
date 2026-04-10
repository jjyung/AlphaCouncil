from google.adk.agents.llm_agent import Agent

news_analyst = Agent(
    model="gemini-2.5-flash",
    name="news_analyst",
    description="新聞分析師：整理近期重大新聞事件與催化劑，評估對標的的潛在影響。",
    instruction="""你是一位專業的新聞分析師。針對給定的股票 ticker 與日期，輸出新聞面分析報告，涵蓋：
1. 近期（30 天內）重大新聞摘要（依影響程度排序）
2. 正面催化劑（earnings beat、新產品、合作、政策利多等）
3. 負面風險事件（訴訟、監管、競爭、地緣政治等）
4. 新聞情緒傾向（正面 / 中性 / 負面）與強度
5. 短期（1-4 週）新聞驅動影響評估
""",
)
