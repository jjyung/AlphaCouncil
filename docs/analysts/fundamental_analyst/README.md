# 基本面分析師 (Fundamentals Analyst)

**職責**：分析財務體質與估值

**使用工具**：

- `get_fundamentals(ticker, market)` → 財務指標

**資料來源**：

- **US 市場**：yfinance（P/E、EPS、Revenue、FCF 等）
- **TW 市場**：yfinance .TW + TWSE OpenAPI（季報、年報、月營收）

**分析指標**：

| 指標類別 | US 市場               | TW 市場                    |
| -------- | --------------------- | -------------------------- |
| 估值     | P/E、P/B、P/S         | P/E、P/B、**現金殖利率**   |
| 獲利能力 | ROE、ROIC、Net Margin | ROE、EPS、**月營收年增率** |
| 成長性   | Revenue Growth YoY    | 營收年增率、季增率         |
| 財務健康 | Debt/Equity、FCF      | 負債比、現金流量比率       |

**TW 特有指標**：

- 現金殖利率（台灣存股文化核心指標）
- 月營收公告（每月 10 日前公布，領先財報）
- 盈餘分配率（配息政策）

**產出欄位**：`fundamentals_report`
