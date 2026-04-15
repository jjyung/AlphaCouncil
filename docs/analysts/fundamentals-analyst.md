# 基本面分析師 (Fundamentals Analyst) 開發方式

## 文件目的

本文件定義 AlphaCouncil 中基本面分析師的開發方式，聚焦於：

- 基本面分析師的角色定位與輸入輸出
- 台股官方公開資料來源選型（TWSE OpenAPI、MOPS、TPEX）
- 美股維持 `yfinance` 原本做法
- 分析框架與指標設計
- 報告生成方式與工程實作規範

本專案以**研究規劃與文件設計**為主，因此本文以可落地的架構與開發約定為核心，不包含實際應用程式實作。

---

## 一、角色定位

基本面分析師負責根據財務報告與估值資料，產出結構化的 `fundamentals_report`，提供後續研究員、大師層與決策層作為基本面依據。

### 主要職責

- 取得個股估值指標（P/E、P/B、殖利率）
- 分析獲利能力（ROE、EPS、Net Margin）
- 分析成長性（營收年增率、季增率）
- 分析財務健康（負債結構、現金流量）
- TW 特有：月營收趨勢判讀、現金殖利率評估、盈餘分配率分析
- 輸出標準化 `fundamentals_report`

### 不負責事項

- 不處理技術指標（MA、RSI、MACD、量價走勢）
- 不解讀新聞事件語氣或公告意涵
- 不分析法人流向、融資融券、借券賣出等籌碼資料
- 不分析市場心理指標（VIX、Put/Call Ratio）
- 不直接產生最終買賣決策

---

## 二、輸入與輸出

### 輸入欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `ticker` | `str` | 股票代碼，例如 `AAPL`、`2330` |
| `date` | `str` | 分析日期，ISO 格式 |
| `market` | `"us" \| "tw"` | 市場別，由前置路由推導 |

### 輸出欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `fundamentals_report` | `str` | 基本面分析師最終報告 |

### 中間資料

基本面分析師在內部處理時，建議維持以下結構化資料物件：

- `valuation_snapshot`：估值倍數與殖利率
- `profitability_data`：獲利能力指標
- `growth_data`：成長性數字（含月營收序列，TW 限定）
- `financial_health_data`：負債結構與現金流量
- `signal_summary`：各指標的判讀摘要

---

## 三、資料來源策略

### 3.1 TW 市場（官方為主）

台股基本面資料有多個官方免費來源，建議以官方資料為主、`yfinance` 為備援。

| 資料類型 | 主要來源 | 說明 |
|----------|----------|------|
| P/E、P/B、現金殖利率 | TWSE OpenAPI（上市） | 官方每日更新，免費、免 API Key |
| P/E、P/B、現金殖利率 | TPEX OpenAPI（上櫃） | 對齊上市口徑，官方、免費 |
| 月營收 | MOPS（公開資訊觀測站） | 每月 10 日前公布，唯一月粒度來源 |
| 季報 / 年報財務數字 | MOPS（公開資訊觀測站） | 損益表、資產負債表、現金流量表 |
| 備援 | `yfinance .TW` / `.TWO` | 快速 snapshot 與交叉驗證，非官方 |

#### TWSE OpenAPI

- 端點 `BWIBBU_ALL`：提供所有上市股票的本益比（P/E）、殖利率、股價淨值比（P/B），每日更新
- 性質：官方、免費、免 API Key，回傳 JSON 格式
- 上市股優先使用此來源的估值快照

#### TPEX OpenAPI

- 提供上櫃股票的本益比﹑殖利率，與 TWSE 口徑對齊
- 性質：官方、免費、免 API Key
- 上櫃股使用此來源，避免混用上市與上櫃的端點

#### MOPS（公開資訊觀測站）

MOPS（mops.twse.com.tw）是台灣所有上市櫃公司財報與自願揭露的法定公告平台，包含：

- **月營收**：每月 10 日前公布，含當月、累計、年增率；是台股最重要的領先財報指標
- **季報**：每季公布損益表、資產負債表、現金流量表；可取得 EPS、ROE、負債比等
- **年報**：完整財務揭露，含盈餘分配率、每股帳面價值等

MOPS 端點多為 HTML 表單型，資料精確度最高，但前處理需求較 OpenAPI 高。月營收為台股特有且不可替代（`yfinance` 不提供月粒度營收），應視為核心資料而非選配。

#### `yfinance .TW` 的定位

- `yfinance` 可提供即時 P/E、EPS、殖利率等快照
- 定位為**備援**與**交叉驗證**，不作為台股基本面主來源
- 在 PoC 或 TWSE / MOPS 端點異常時作為降級方案

#### 選型取捨

- TWSE / TPEX OpenAPI 的估值欄位每日快照取得方便，結構化程度高
- MOPS 月營收為台股特有且不可替代（`yfinance` 不提供月粒度資料），須獨立處理
- `yfinance .TW` 可作備援，但非官方來源，欄位品質不一致

---

### 3.2 US 市場（yfinance 維持原做法）

美股維持原本使用 `yfinance` 的方式，不調整：

| 資料物件 | `yfinance` 方法 | 說明 |
|----------|-----------------|------|
| 估值摘要 | `ticker.info` | P/E、EPS、P/B、市值、股息殖利率 |
| 損益表（年度） | `ticker.financials` | Revenue、Net Income 等 |
| 資產負債表 | `ticker.balance_sheet` | Total Debt、Equity 等 |
| 現金流量表 | `ticker.cashflow` | FCF、Operating Cash Flow 等 |
| 季度損益表 | `ticker.quarterly_financials` | 季度 Revenue、EPS |
| 季度現金流 | `ticker.quarterly_cashflow` | 季度 FCF |

---

### 3.3 選型結論

| 優先級 | TW 資料源 | 適用場景 |
|--------|-----------|----------|
| 1 | TWSE OpenAPI | 上市股 P/E、殖利率、P/B 每日快照 |
| 1 | TPEX OpenAPI | 上櫃股 P/E、殖利率、P/B 每日快照 |
| 2 | MOPS | 月營收序列、季報財務指標、年報盈餘分配 |
| 3 | `yfinance .TW` / `.TWO` | 備援、快速 PoC、交叉驗證 |

US 市場僅使用 `yfinance`，無分軌。

---

## 四、資料路由策略

| 條件 | 路由 |
|------|------|
| `market == "us"` | 使用 `yfinance` |
| `market == "tw"` 且上市 | 估值：TWSE OpenAPI；財報：MOPS |
| `market == "tw"` 且上櫃 | 估值：TPEX OpenAPI；財報：MOPS |
| TWSE / TPEX 失敗 | fallback `yfinance .TW` |
| MOPS 失敗 | fallback `yfinance .TW`（僅年度財報，月營收無替代） |

#### 台股 ticker 正規化

- 內部主鍵：`2330`（純數字，不含 suffix）
- 上市判定：掛牌於 TWSE → suffix `.TW`
- 上櫃判定：掛牌於 TPEX → suffix `.TWO`
- 判定方式建議以掛牌別靜態映射表為主，不依賴 ticker 格式盲猜

---

## 五、分析框架

### 5.1 估值分析

**核心問題**：目前股價是否合理？是否有估值溢價或折價？

| 指標 | US 市場 | TW 市場 |
|------|---------|---------|
| 本益比 | P/E Ratio | P/E Ratio（TWSE / TPEX） |
| 淨值比 | P/B Ratio | P/B Ratio（TWSE / TPEX） |
| 現金殖利率 | Dividend Yield | **現金殖利率**（TWSE / TPEX，台灣存股核心指標） |
| 股價銷售比 | P/S Ratio（yfinance） | — |

**TW 特有判讀**

- 台股高度重視現金殖利率，常見以 5% 作為存股基準門檻
- 殖利率需搭配配息穩定性與 EPS 趨勢共同判斷，不可單獨使用
- P/E 解讀需考量產業別，半導體、金融、傳產的合理區間差異顯著

---

### 5.2 獲利能力

**核心問題**：公司每年賺多少？能否持續獲利？

| 指標 | US 市場 | TW 市場 |
|------|---------|---------|
| 股東權益報酬率 | ROE | ROE（MOPS 季報） |
| 淨利率 | Net Margin | Net Margin（MOPS 季報） |
| 每股盈餘 | EPS | EPS（MOPS 季報） |
| 資本報酬率 | ROIC | — |

---

### 5.3 成長性

**核心問題**：公司正在成長還是衰退？成長速度如何？

| 指標 | US 市場 | TW 市場 |
|------|---------|---------|
| 年度營收成長率 | Revenue Growth YoY | 營收年增率（MOPS） |
| 季增率 | Quarterly Revenue QoQ | 月營收季增率（MOPS） |
| 月營收年增率 | — | **月營收年增率**（MOPS，台股核心領先指標） |

**TW 特有判讀：月營收趨勢**

月營收是台股最重要的**領先財報指標**。規劃如下：

- 月營收每月 10 日前於 MOPS 公布，領先季報約 1–2 個月
- 月營收年增率（YoY）連續 3 個月轉正，通常先於季報反映改善趨勢
- 月營收年增率連續 3 個月轉負，常作為財務轉差的早期訊號
- 需同時觀察累計營收年增率，單月波動可能受假期與業務週期干擾

---

### 5.4 財務健康

**核心問題**：公司財務結構是否穩健？能否應對景氣波動？

| 指標 | US 市場 | TW 市場 |
|------|---------|---------|
| 負債結構 | Debt/Equity Ratio | 負債比（MOPS 季報） |
| 自由現金流 | FCF | 現金流量比率（MOPS 季報） |
| 流動性 | Current Ratio（選配） | 流動比率（選配，MOPS 年報） |

---

### 5.5 TW 特有子模組

| 指標 | 來源 | 分析重點 |
|------|------|----------|
| 月營收趨勢 | MOPS | 連續月份 YoY 方向是否一致 |
| 現金殖利率 | TWSE / TPEX OpenAPI | 是否達存股門檻（通常 ≥ 5%） |
| 盈餘分配率 | MOPS 年報 | 配息政策穩定性評估，高配息是否可持續 |

---

## 六、與其他分析師邊界

| 類別 | 歸屬分析師 |
|------|------------|
| P/E、P/B、殖利率、EPS、ROE、月營收 | **Fundamentals Analyst** |
| 法人現貨買賣超、融資融券、借券賣出 | Chip Analyst |
| MA、RSI、MACD、KD、量價 | Technical Analyst |
| VIX、Put/Call Ratio、恐慌程度 | Psychology Analyst |
| 新聞事件解讀、公告語氣判斷 | News Analyst |

---

## 七、分析流程設計

建議將基本面分析師拆成四個固定步驟：

### Step 1：取得估值快照

- TW 上市：呼叫 TWSE OpenAPI 取得 P/E、P/B、現金殖利率
- TW 上櫃：呼叫 TPEX OpenAPI 取得同口徑欄位
- US：呼叫 `yfinance ticker.info`
- 結果寫入 `valuation_snapshot`

### Step 2：取得獲利能力與財務健康資料

- TW：呼叫 MOPS 取得最近一期季報；計算 ROE、EPS、Net Margin、負債比、現金流量比率
- US：呼叫 `yfinance` 相關財報物件；計算同類指標
- 結果寫入 `profitability_data`、`financial_health_data`

### Step 3：取得成長性資料（TW 含月營收）

- TW：呼叫 MOPS 取得近 12 個月月營收序列；計算月 YoY、累計 YoY、趨勢方向
- TW：同步計算季度營收 YoY 與 QoQ
- US：以 `yfinance quarterly_financials` 計算 Revenue YoY / QoQ
- 結果寫入 `growth_data`

### Step 4：生成報告

- 彙整三節：**估值摘要 / 獲利與成長 / 財務健康**
- 條列 TW 特有指標：月營收趨勢、現金殖利率、盈餘分配率
- 標記異常或值得關注的風險因子
- 輸出 `fundamentals_report`

---

## 八、報告結構

`fundamentals_report` 建議內部分成三節：

```markdown
### 基本面分析師報告

**分析日期**：YYYY-MM-DD
**標的**：{ticker} ({market})

#### 摘要

- [關鍵發現 1]
- [關鍵發現 2]
- [關鍵發現 3]

#### 估值摘要

- P/E: 數值（與產業均值比較）
- P/B: 數值
- 現金殖利率: 數值（TW 市場）

#### 獲利與成長

- ROE: 數值（近一季）
- EPS: 數值（近一季 / 年度）
- 月營收年增率: 數值（TW 市場）+ 趨勢方向（連續幾個月？）
- Net Margin: 數值

#### 財務健康

- 負債比 / Debt/Equity: 數值
- FCF / 現金流量比率: 數值

#### 風險提示

- [若有估值過高、獲利衰退、負債偏高等異常，特別說明]
```

---

## 九、推薦落地方案

1. 先以 TWSE OpenAPI `BWIBBU_ALL` 端點建立上市股估值快照流程
2. 上櫃股改用 TPEX OpenAPI 同口徑端點，ticker 路由依掛牌別靜態映射
3. 月營收資料另開 MOPS 取用流程，獨立維護（欄位結構與 OpenAPI 不同）
4. 季報財務指標以 MOPS 為主，`yfinance .TW` 作備援，避免過依賴非官方來源
5. US 市場不調整，維持原本 `yfinance` 主流程
6. `fundamentals_report` 固定分成三節：**估值摘要 / 獲利與成長 / 財務健康**
7. 月營收趨勢建議單獨呈現連續月份 YoY 方向，不只看最新一個月數字

---

## 參考文件

- [分析師層總覽](./README.md)
- [籌碼分析師開發方式](./chip-analyst.md)
- [技術分析師開發方式](./technical-analyst.md)
- [市場心理分析師開發方式](./psychology-analyst.md)
- [AlphaCouncil 外部資料來源說明](../../external-data.md)
