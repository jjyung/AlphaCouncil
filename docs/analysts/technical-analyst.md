# 技術分析師 (Technical Analyst) 開發方式

## 文件目的

本文件定義 AlphaCouncil 中技術分析師的開發方式，聚焦於：

- 技術分析師的角色定位與輸入輸出
- 台股免費資料來源選型
- 資料路由與指標計算策略
- 報告生成方式與工程實作規範

本專案以**研究規劃與文件設計**為主，因此本文以可落地的架構與開發約定為核心，不包含實際應用程式實作。

---

## 一、角色定位

技術分析師負責根據價格、成交量、趨勢、動能與波動資料，產出結構化的 `technical_report`，提供後續研究員、交易員與風險管理角色作為決策輸入。

### 主要職責

- 取得個股 OHLCV 歷史資料
- 取得市場基準指數資料，用於相對強弱比較
- 計算固定技術指標集
- 判讀趨勢、動能、波動與量價關係
- 輸出標準化技術分析報告

### 不負責事項

- 不直接產生最終買賣決策
- 不進行基本面、新聞、情緒面解讀
- 不依賴即時盤中高頻資料

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
| `technical_report` | `str` | 技術分析師最終報告 |

### 中間資料

技術分析師在內部處理時，建議維持以下結構化資料物件：

- `price_df`：個股日 OHLCV 資料
- `benchmark_df`：市場基準指數日 OHLCV 資料
- `indicator_df`：指標計算結果
- `signal_summary`：規則判讀後的訊號摘要

---

## 三、台股免費資料來源選型

考量 Technical Analyst 的核心需求是**快速取得穩定的日 OHLCV 與市場基準資料**，而不是一次抓取大量官方欄位後再自行整理，因此台股資料來源建議改採「**`yfinance` 為主、官方 API 為輔**」策略。

此取捨的核心原因如下：

- 技術分析主要依賴 OHLCV，`yfinance` 已能直接提供標準化資料
- `yfinance` 的欄位結構與 US 市場一致，能降低 US / TW 雙市場開發成本
- 若改以 TWSE / TPEX 為主，仍需額外整理上市 / 上櫃路由、欄位對應與指標前處理
- 在研究型、多 agent 架構下，資料取得延遲通常比官方欄位完整性更影響整體體驗

### 3.1 首選方案：`yfinance`

#### 適用性評估

以台股 Technical Analyst 需求來看，`yfinance` 對台灣市場屬於**足夠支援**，原因是它已覆蓋技術分析最核心的三類資料：

| 資料類型 | `yfinance` 台股支援情況 | 評估 |
|----------|--------------------------|------|
| 上市股票日 OHLCV | 支援，代碼格式 `2330.TW` | 足夠 |
| 上櫃股票日 OHLCV | 支援，代碼格式 `6488.TWO` | 足夠 |
| 台股基準指數 | 支援，例如 `^TWII`、`^TWOII` | 足夠 |
| ETF / 大盤代理商品 | 支援，例如 `0050.TW` | 足夠 |
| 公司行為資料 | 支援股息、分割等欄位 | 可用 |

#### 實際可用性觀察

實際檢查 Yahoo Finance chart 端點，可取得以下資料：

- `2330.TW`：可回傳日 OHLCV、時區 `Asia/Taipei`、交易所 `TAI`
- `6488.TWO`：可回傳日 OHLCV、時區 `Asia/Taipei`、交易所 `TWO`
- `^TWII`：可回傳加權指數日 OHLC
- `^TWOII`：可回傳櫃買指數日 OHLC
- `0050.TW`：可回傳 ETF 日 OHLCV，可作替代性市場觀察標的

這代表對 Technical Analyst 最關鍵的「個股日線 + 基準指數 + 量價欄位」，`yfinance` 已具備可落地能力。

#### 優點

- 單一介面即可處理 US / TW 市場
- 欄位天然接近 DataFrame 分析流程，指標計算前處理較少
- 多數技術分析僅需 `history()` 或 `download()` 即可完成
- 對研究用途來說，開發速度與維護成本明顯優於官方 API 雙軌整合

#### 限制

- 非官方來源，無 SLA 保證
- 最新一根 bar 在盤中或收盤前後可能為 `null` 或未定稿
- 台股部分 metadata 品質不完全一致，例如某些指數名稱欄位較不穩定
- 若未來擴充到非技術面的台股特有資料，仍需其他資料源補足

#### 結論

若目標是 **Technical Analyst 的主流程**，`yfinance` 對台股已經足夠；因為技術分析師聚焦在 OHLCV、量價、趨勢、動能與基準比較，而這些資料 `yfinance` 已可直接提供。

### 3.2 輔助方案：官方免費 API

#### TWSE OpenAPI

- 性質：官方、免費、免 API Key
- 適用範圍：上市股票、加權指數、市場統計
- 適合用途：補官方欄位、交叉驗證、異常排查

**建議使用端點**

| 端點 | 用途 | 技術分析用途 |
|------|------|--------------|
| `/exchangeReport/STOCK_DAY_ALL` | 上市個股日資料 | 個股日線主來源 |
| `/indicesReport/MI_5MINS_HIST` | 加權指數歷史 OHLC | 相對強弱基準 |
| `/exchangeReport/MI_INDEX` | 大盤收盤與指數資訊 | 市場背景判讀 |
| `/exchangeReport/FMTQIK` | 市場總成交量值與 TAIEX | 市場量價熱度 |

#### TPEX OpenAPI

- 性質：官方、免費、免 API Key
- 適用範圍：上櫃股票、櫃買指數、市場統計
- 適合用途：補官方欄位、交叉驗證、異常排查

**建議使用端點**

| 端點 | 用途 | 技術分析用途 |
|------|------|--------------|
| `/tpex_mainboard_quotes` | 上櫃個股日資料 | 上櫃日線主來源 |
| `/tpex_index` | 櫃買指數歷史 OHLC | 相對強弱基準 |
| `/tpex_reward_index` | 櫃買報酬指數 | 含配息基準比較 |
| `/tpex_daily_trading_index` | 上櫃市場總成交量值與指數 | 市場背景判讀 |

### 3.3 其他免費 lib

#### `twstock`

- 性質：免費 Python library
- 優點：台股整合方便，對台股代碼與基本操作友善
- 限制：底層仍依賴 TWSE / TPEX 資料，需注意 request limit
- 適合用途：快速 PoC、簡化台股代碼處理、作為輕量備援

#### `yfinance`

- 性質：免費 Python library
- 優點：US / TW 可共用相同介面，便於跨市場一致化
- 限制：非官方 Yahoo 來源，仍需保留 fallback 與資料驗證策略
- 適合用途：台股 Technical Analyst 主來源、跨市場共用主來源

### 3.4 資料源選型結論

| 優先級 | 資料源 | 建議角色 |
|--------|--------|----------|
| 1 | `yfinance` | 台股 Technical Analyst 主來源 |
| 2 | `twstock` | 台股輕量備援 |
| 3 | TWSE OpenAPI / TPEX OpenAPI | 官方欄位補充與交叉驗證 |

---

## 四、資料路由策略

台股資料雖以 `yfinance` 為主，但仍不可只靠 ticker suffix 盲猜，建議先做市場與掛牌別判定，再決定 `.TW` 或 `.TWO`。

### 4.1 路由規則

| 條件 | 路由 |
|------|------|
| `market == "us"` | 使用 US 資料流 |
| `market == "tw"` 且上市 | 優先使用 `ticker.TW` |
| `market == "tw"` 且上櫃 | 優先使用 `ticker.TWO` |
| `yfinance` 失敗 | fallback `twstock` |
| `twstock` 失敗且需官方交叉驗證 | 使用 TWSE / TPEX OpenAPI |

### 4.2 台股 ticker 正規化

建議建立標準化函式：

- `2330` -> `2330`（內部主鍵）
- 若使用 `yfinance`：上市轉 `2330.TW`
- 若使用 `yfinance`：上櫃轉 `6488.TWO`

### 4.3 市場基準對應

| 標的類型 | 建議基準 |
|----------|----------|
| 上市股票 | `^TWII` 或 `0050.TW` |
| 上櫃股票 | `^TWOII` |

### 4.4 基準選型建議

| 基準 | 用途 | 建議程度 |
|------|------|----------|
| `^TWII` | 上市股票相對強弱主基準 | 高 |
| `^TWOII` | 上櫃股票相對強弱主基準 | 高 |
| `0050.TW` | ETF 型代理基準、做商品型比較 | 中 |

若 `^TWOII` 品質不穩或 metadata 異常，可保留 TPEX 官方指數資料作驗證，但主流程仍建議先走 `yfinance`。

---

## 五、資料模型標準化

無論資料源來自 `yfinance`、`twstock`、TWSE 或 TPEX，都應先轉成統一欄位格式再進行指標計算。

### 5.1 標準欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `date` | `datetime` | 交易日 |
| `open` | `float` | 開盤價 |
| `high` | `float` | 最高價 |
| `low` | `float` | 最低價 |
| `close` | `float` | 收盤價 |
| `volume` | `float` | 成交量 |
| `turnover` | `float` | 成交金額，可選 |

### 5.2 前處理規範

- 日期排序必須由舊到新
- 移除重複交易日
- 缺值先做檢查，再決定前值填補或捨棄該筆
- 成交量與價格欄位需統一轉成數值型別
- 與基準指數比較前，先以交易日交集對齊

---

## 六、技術指標設計

技術分析師不依賴外部指標 API，改採「**從 `yfinance` 取得原始 OHLCV，再自行計算固定指標集**」策略，確保可重現與跨市場一致性。

### 6.0 職責邊界

為避免多 agent 職責重疊，Technical Analyst 與其他分析師的邊界建議明確如下：

| 類別 | 歸屬分析師 | 範例 |
|------|------------|------|
| 價格趨勢 | Technical Analyst | MA、趨勢線、突破/跌破 |
| 動能 | Technical Analyst | MACD、RSI、KD |
| 波動 | Technical Analyst | Bollinger、波動率、區間收斂 |
| 量價 | Technical Analyst | 成交量、量增價漲、量縮整理 |
| 相對強弱 | Technical Analyst | 個股相對 `^TWII` / `^TWOII` |
| 籌碼 | Chip Analyst | 三大法人、融資融券、借券賣出 |
| 市場情緒 / 心理 | Psychology Analyst | VIX、Put/Call Ratio、社群熱度 |

本文件中的「量價分析」僅包含成交量與價格互動，不包含法人流向、融資融券或借券賣出等籌碼資料。

### 6.1 固定指標集

| 類別 | 指標 | 用途 |
|------|------|------|
| 趨勢 | MA5、MA20、MA60 | 判斷短中期趨勢 |
| 動能 | MACD、MACD Signal、Histogram | 判讀趨勢動能與轉折 |
| 動能 | RSI14 | 偵測超買超賣 |
| 動能 | KD(9,3,3) | 判斷短線轉折 |
| 波動 | Bollinger Bands(20,2) | 觀察波動區間與擠壓 |
| 量價 | Volume、Volume MA5、Volume MA20 | 驗證量價結構 |
| 相對表現 | Relative Strength vs Benchmark | 比較個股是否強於大盤 |

### 6.2 指標計算原則

- MA 使用簡單移動平均即可，先避免過度複雜化
- RSI 預設使用 14 日
- KD 使用 9,3,3 固定參數
- Bollinger 使用 20 日均線與 2 倍標準差
- Relative Strength 以個股報酬率對比基準報酬率，不直接使用外部 RS 分數

### 6.3 套件建議

| 選項 | 建議程度 | 說明 |
|------|----------|------|
| `pandas` + 自行實作 | 高 | 最可控，文件與實作一致 |
| `pandas` + `ta` | 高 | 維護成本低，研究用足夠 |
| `pandas` + `pandas-ta` | 中 | 功能完整，但需評估相依性 |

---

## 七、分析流程設計

建議將技術分析師拆成五個固定步驟，避免完全交由 LLM 自由發揮。

### Step 1：取得資料

- 個股至少抓取最近 120 個交易日
- 基準指數至少抓取相同區間
- 若資料少於 60 個交易日，標記分析可信度下降

### Step 2：計算指標

- 對 `price_df` 計算所有固定指標
- 保留最近 20 個交易日作為報告觀察視窗

### Step 3：規則判讀

以 deterministic rule 先產出訊號，不直接依賴 LLM 判斷。

**建議規則範例**：

- `close > MA20 > MA60` -> 中期多頭排列
- `MACD > Signal` 且 Histogram 轉正 -> 動能改善
- `RSI > 70` -> 可能短線過熱
- `K 上穿 D` -> 短線轉強訊號
- `close 接近 Bollinger Upper` 且爆量 -> 注意追價風險
- `個股 20 日漲幅 > 基準 20 日漲幅` -> 相對強勢

### Step 4：產生結構化摘要

建議輸出：

- 趨勢判斷
- 動能判斷
- 波動判斷
- 量價判斷
- 相對強弱判斷
- 主要風險提示

### Step 5：生成 `technical_report`

可由 LLM 將規則化結果整理成自然語言，但不可改寫核心數值與訊號方向。

---

## 八、報告格式規範

技術分析師輸出格式建議如下：

```markdown
### 技術分析師報告

**分析日期**：2026-04-15
**標的**：2330（TW Market）
**基準**：TAIEX

#### 摘要
- 中期趨勢維持多頭排列
- MACD 與 KD 顯示短線動能轉強
- 股價接近布林上軌，需留意追價風險

#### 趨勢分析
- MA5、MA20、MA60 排列為 ...

#### 動能分析
- MACD 為 ...
- RSI14 為 ...
- KD 為 ...

#### 波動與量價分析
- 布林通道寬度為 ...
- 近 5 日平均量相較 20 日平均量 ...

#### 相對強弱
- 相較加權指數，近 20 日表現 ...

#### 風險提示
- ...
```

### 報告要求

- 摘要優先寫出 3 個最重要訊號
- 每個結論盡量附對應指標依據
- 避免使用模糊措辭，例如「可能不錯」
- 若資料不足，必須明確標示可信度限制

---

## 九、工程實作建議

### 9.1 模組切分

建議以四層設計：

| 層級 | 職責 |
|------|------|
| `providers/` | 對接 `yfinance`、`twstock`、TWSE、TPEX |
| `normalizers/` | 統一資料欄位格式 |
| `indicators/` | 計算 MA、MACD、RSI、KD、Bollinger |
| `analysts/technical_analyst` | 聚合資料、規則判讀、輸出報告 |

### 9.2 Tool 介面建議

若未來以 ADK Function Tool 落地，建議至少提供以下工具：

| Tool | 說明 |
|------|------|
| `get_stock_data(ticker, start, end, market)` | 以 `yfinance` 為主取得個股 OHLCV |
| `get_market_index(start, end, market, board)` | 以 `^TWII` / `^TWOII` 取得市場基準 |
| `get_technical_indicators(ticker, start, end, market)` | 回傳已計算指標 |

### 9.3 快取與重試

- 同一次分析流程中，相同參數的資料請求應快取
- 官方 API 呼叫失敗時應重試 2 至 3 次
- 若主來源 `yfinance` 失敗，依序 fallback 至 `twstock`、官方 API
- 每次 fallback 都應記錄來源，便於報告與除錯

### 9.4 例外處理

| 情境 | 建議處理 |
|------|----------|
| 查無 ticker | 回傳明確錯誤，不進行後續分析 |
| 資料天數不足 | 降級報告可信度，仍可做有限分析 |
| 基準資料缺失 | 跳過相對強弱段落，保留個股技術分析 |
| 某個輔助端點失敗 | 不中斷主流程，僅省略該輔助判讀 |

---

## 十、與其他分析師的責任切分

### Technical Analyst 負責

- 個股 OHLCV 資料取得
- 基準指數資料取得
- MA、MACD、RSI、KD、Bollinger、Volume 等技術指標
- 趨勢、動能、波動、量價、相對強弱分析

### Technical Analyst 不負責

- 三大法人買賣超
- 融資融券餘額與資券比
- 借券賣出與放空券源
- 社群情緒與新聞情緒

### 建議分工

- Technical Analyst：專注圖表與價格行為
- Psychology Analyst：專注波動、恐慌與風險偏好
- Chip Analyst：專注法人、融資融券與借券等籌碼面
- Fundamentals Analyst：專注財報、估值與成長

---

## 十一、品質驗證方式

### 資料層驗證

- 抽驗上市與上櫃各至少 3 檔股票
- 比對官方網站顯示值與 API 回傳值
- 驗證日期排序、欄位型別、缺值處理

### 指標層驗證

- 以固定測試資料驗證 MA、MACD、RSI、KD、Bollinger 結果
- 與常見圖表軟體或 Python 套件計算值交叉比對

### 報告層驗證

- 確認報告中的文字敘述與指標數值一致
- 確認資料不足時會出現風險提示
- 確認 US / TW 輸出格式一致，但基準市場不同

---

## 十二、推薦落地方案

若以 AlphaCouncil 現有規劃為基礎，台股 Technical Analyst 建議採用以下方案：

1. 台股主資料以 `yfinance` 為核心
2. 技術指標統一在本地計算，不依賴外部指標 API
3. `twstock` 作為台股輕量備援
4. TWSE / TPEX 官方 API 僅作交叉驗證與補官方行情欄位
5. 以 deterministic rule 先產生訊號，再由 LLM 組裝報告文字

此方案的優點是：免費、開發快、跨市場一致、前處理成本低，且更符合多 agent 研究系統對回應速度的需求。

---

## 十三、yfinance 是否足夠支援台股

結論是：**對 Technical Analyst 而言，足夠。**

### 足夠的部分

- 台股上市與上櫃股票皆可用 `.TW` / `.TWO` 取得日 OHLCV
- 可取得台股主要基準指數，例如 `^TWII`、`^TWOII`
- 可直接支援 MA、MACD、RSI、KD、Bollinger、量價分析
- 可與 US 市場共享相同下載與清洗流程

### 不足的部分

- 不適合作為官方資料對帳依據
- 不保證每次都能穩定取得最新盤後最終值
- 某些 metadata 欄位在台股指數上可能品質不一

### 實務建議

- Technical Analyst 主流程：直接採用 `yfinance`
- 若要做研究驗證或異常排查：保留官方 API 抽查能力
- 若 `^TWOII` 穩定性不足：允許以 TPEX 指數資料作備援

---

## 參考文件

- [分析師層總覽](./README.md)
- [AlphaCouncil 外部資料來源說明](../../external-data.md)
- [AlphaCouncil 決策執行流程](../../workflow.md)
- [TradingAgents 外部資料源說明](../../../TradingAgents/external-data.md)
