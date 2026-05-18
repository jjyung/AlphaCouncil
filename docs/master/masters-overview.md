# AI 對沖基金大師代理總覽與重構評估

本文件整理 `ai-hedge-fund` 內 13 位投資大師代理的分析方法，目標是回答以下重構問題：

1. 這些大師的方法是否有共同骨幹。
2. 哪些指標與能力可以共用，哪些需要個別實作。
3. 每位大師依賴哪些資料與模組。
4. 是否適合分工開發，以及建議的拆分方式。

---

## 結論摘要

結論不是「13 位大師就要做 13 套完全獨立系統」，而是「共用同一個分析平台，再為每位大師配置不同的評分規則、權重與敘事層」。

從目前 `sources/ai-hedge-fund/src/agents/` 的結構來看，大師代理大致共享同一個四層骨架：

1. **共用資料擷取層**：抓取財報、line items、市值、價格、內部人交易、公司新聞。
2. **共用分析能力層**：成長、獲利、槓桿、現金流、估值、波動、情緒、內部人行為等基礎因子。
3. **大師策略組裝層**：每位大師選擇自己重視的因子，設定不同閾值、權重與決策規則。
4. **輸出與編排層**：統一寫回 `analyst_signals`，再交由 `risk_manager` 與 `portfolio_manager` 使用。

因此，**建議重做方式是「共用底層能力 + 個別實作策略配置」**，而不是每位大師都從資料抓取、指標計算、訊號輸出一路重做。

如果以重構工作量粗估：

- 約 **60% 到 75%** 可共用。
- 約 **25% 到 40%** 需要保留大師個別化。

---

## 共用骨幹

### 共用資料來源

大多數大師直接或間接共用以下資料存取能力：

| 共用能力 | 用途 | 主要使用者 |
| --- | --- | --- |
| `get_financial_metrics()` | ROE、ROIC、營收、利潤率、槓桿等財務指標 | 幾乎全部大師 |
| `search_line_items()` | FCF、股本、債務、CapEx、股利等細部項目 | 幾乎全部大師 |
| `get_market_cap()` | 估值、安全邊際、市值比較 | 幾乎全部大師 |
| `get_insider_trades()` | 管理層 alignment、skin in the game、逆向訊號 | Munger、Burry、Lynch、Fisher、Druckenmiller、Taleb |
| `get_company_news()` | 情緒、敘事風險、逆向訊號、黑天鵝哨兵 | Munger、Burry、Lynch、Fisher、Druckenmiller、Taleb |
| `get_prices()` | 波動、動能、尾部風險、風險報酬 | Taleb、Druckenmiller、risk_manager |

### 共用指標族群

雖然各大師命名不同，但底層其實反覆出現同幾類指標：

| 指標族群 | 典型內容 | 可否共用 |
| --- | --- | --- |
| 獲利品質 | ROE、ROIC、營業利益率、毛利率 | 可高度共用 |
| 成長品質 | 營收 CAGR、盈餘成長、FCF 成長 | 可高度共用 |
| 財務穩健 | 負債比、流動比率、利息保障倍數 | 可高度共用 |
| 現金流品質 | FCF、owner earnings、FCF yield | 可高度共用 |
| 估值 | DCF、Graham Number、EV/EBITDA、本益比比較 | 可部分共用 |
| 管理層品質 | 資本配置、庫藏股、股利、內部人買賣 | 可部分共用 |
| 市場情緒 | 新聞情緒、逆向情緒、敘事偏誤 | 可部分共用 |
| 價格風險 | 波動率、回撤、動能、偏態 | Taleb/Druckenmiller 可共用 |
| 非對稱性 | 上檔空間、下檔保護、convexity | 需抽象化後共用 |

### 共用程式骨架

每位大師代理的主流程都非常接近：

1. 從 `state` 讀取 `tickers` 與日期。
2. 抓取該大師需要的資料。
3. 執行數個 `analyze_*()` / `calculate_*()` 函式。
4. 產出中間分析結果與 score。
5. 呼叫 `generate_*_output()` 讓 LLM 生成最終 `signal/confidence/reasoning`。
6. 寫回 `state["data"]["analyst_signals"]`。

這表示未來重構時，非常適合抽成統一框架，例如：

- `MasterAgentBase`
- `DataRequirement`
- `FactorBundle`
- `SignalComposer`
- `NarrativeRenderer`

---

## 哪些一定要個別實作

以下部分不適合完全共用，否則大師之間會失去策略辨識度：

### 1. 決策哲學與權重

- Buffett 重視護城河、資本效率、owner earnings。
- Graham 重視安全邊際、資產保護、財務安全。
- Damodaran 重視故事與數值驅動的一致性、DCF 敏感度。
- Taleb 重視脆弱性、尾部風險、凸性與 skin in the game。
- Druckenmiller 重視成長、動能、風險報酬不對稱。
- Cathie Wood 重視創新、TAM、顛覆式成長。

同樣都是「估值」或「成長」，每位大師看的是不同定義與不同容忍區間，這部分應保留策略配置差異。

### 2. 特定分析邏輯

某些分析函式有明顯大師專屬性：

- Damodaran 的 `calculate_intrinsic_value_dcf()`
- Buffett 的 `calculate_owner_earnings()` 與 `analyze_pricing_power()`
- Graham 的 `analyze_valuation_graham()`
- Taleb 的 `analyze_tail_risk()`、`analyze_convexity()`、`analyze_black_swan_sentinel()`
- Druckenmiller 的 `analyze_growth_and_momentum()`、`analyze_risk_reward()`
- Cathie Wood 的 `analyze_disruptive_potential()`

這些不應硬抽成單一通用函式，但可以建立共用底層計算元件，再由各策略組合。

### 3. Prompt 與敘事層

目前每位大師都用不同的 `generate_*_output()` 提示詞，這不是單純文案差異，而是最後決策偏好的顯式規格。

可共用的是：

- JSON schema
- LLM 呼叫介面
- prompt 組裝框架

不應共用的是：

- 人設語氣
- 決策 checklist
- bullish / bearish / neutral 的判定語意
- confidence 的定義標準

---

## 大師分群評估

### A. 價值與品質投資群

成員：Buffett、Munger、Graham、Pabrai、Ackman、Burry、Jhunjhunwala、Damodaran

共同點：

- 高度依賴財務報表、line items、市值。
- 重視安全邊際、資本效率、槓桿控制、現金流。
- 估值是核心模組。

重構建議：

- 可共用一個 `value_quality_factor_pack`。
- 內含 ROE、ROIC、margin、debt、interest coverage、FCF yield、earnings stability、intrinsic value 等基礎能力。
- 再由各大師做不同的 score mapping 與敘事。

### B. 成長與敘事投資群

成員：Cathie Wood、Peter Lynch、Phil Fisher、部分 Druckenmiller

共同點：

- 重視營收成長、可擴張市場、管理層執行力。
- 對新聞、產業故事、產品創新更敏感。
- 可接受較高估值，但需要成長合理化。

重構建議：

- 可共用 `growth_narrative_factor_pack`。
- 內含 revenue growth、margin trend、R&D proxy、PEG / growth-adjusted valuation、news / insider overlays。

### C. 事件驅動與逆向群

成員：Burry、Ackman、部分 Pabrai

共同點：

- 都關注市場錯價與催化劑。
- 會重視資產負債表、防守性、管理行動、資本重組機會。

重構建議：

- 可共用 `catalyst_contrarian_pack`。
- 包含 insider、buyback/dividend、balance-sheet stress、news negativity vs fundamentals。

### D. 風險結構與價格行為群

成員：Taleb、Druckenmiller

共同點：

- 都依賴 `get_prices()`，不能只靠財報。
- 關心波動、價格結構、非對稱風險報酬。

差異：

- Taleb 偏脆弱性、尾部風險、skin in the game。
- Druckenmiller 偏動能、催化、上漲趨勢與進攻式風險報酬。

重構建議：

- 共用 `market_regime_pack`。
- 個別保留 `tail_risk_pack` 與 `momentum_pack`。

---

## 各大師方法、共用度與依賴

| 大師 | 核心方法 | 可共用部分 | 必須個別實作 | 主要依賴 |
| --- | --- | --- | --- | --- |
| Warren Buffett | 護城河、資本效率、owner earnings、內在價值 | 財務品質、成長、估值基礎計算 | pricing power、book value growth、Buffett 判定規則 | 財務指標、line items、市值 |
| Charlie Munger | 護城河、管理品質、可預測性、合理價格買好公司 | Buffett 類品質因子、估值底層、insider/news 模組 | mental models 式整體判斷、predictability 組裝 | 財務指標、line items、市值、內部人、新聞 |
| Ben Graham | 財務安全、安全邊際、保守估值 | 財務穩健、價值因子、line items 抽取 | Graham Number / NCAV 規則、保守門檻 | 財務指標、line items、市值 |
| Bill Ackman | 高品質企業、FCF、資本配置、激進改革潛力 | 品質、FCF、槓桿、估值模組 | activism potential、催化劑判讀 | 財務指標、line items、市值 |
| Cathie Wood | 顛覆式創新、高 TAM、高成長 | 成長因子、估值底層 | disruptive potential、innovation narrative | 財務指標、line items、市值 |
| Aswath Damodaran | 故事轉數字、DCF、相對估值、風險調整 | 成長、風險、估值元件 | story-to-numbers、DCF 敏感度框架 | 財務指標、line items、市值 |
| Michael Burry | 深度價值、逆向、資產負債表、防守優先 | 價值、財務壓力、insider/news 模組 | contrarian sentiment 與 Burry 式催化判斷 | 財務指標、line items、市值、內部人、新聞 |
| Mohnish Pabrai | downside protection、低風險翻倍 | 價值、FCF、槓桿、防守因子 | double potential、Pabrai checklist | 財務指標、line items、市值 |
| Peter Lynch | GARP、PEG、十倍股、好故事 | 成長、估值、insider/news 模組 | ten-bagger 敘事、Lynch 式實用判斷 | line items、市值、內部人、新聞 |
| Phil Fisher | 長期成長、管理層、研發與 scuttlebutt | 成長、利潤率、管理效率、insider/news 模組 | scuttlebutt 對應的敘事組裝 | line items、市值、內部人、新聞 |
| Rakesh Jhunjhunwala | 品質成長、管理層、長期持有、安全邊際 | 成長、獲利、財務穩健、估值底層 | Jhunjhunwala 風格組裝與判準 | 財務指標、line items、市值 |
| Stanley Druckenmiller | 成長、動能、情緒、非對稱風險報酬 | 成長、sentiment、insider、price-based 模組 | momentum + asymmetric risk/reward 判斷 | 財務指標、line items、市值、內部人、新聞、價格 |
| Nassim Taleb | antifragility、tail risk、convexity、fragility | 價格風險、槓桿、insider/news 模組 | tail risk、convexity、black swan sentinel、vol regime | 價格、財務指標、line items、市值、內部人、新聞 |

---

## 依賴關係評估

### 最底層依賴

所有大師幾乎都依賴下列底層能力，應先做完再往上疊策略：

1. 財務資料擷取與正規化。
2. line items 抽取與欄位映射。
3. 市值與價格資料統一介面。
4. 共用 signal schema 與 agent state schema。
5. 共用 LLM 呼叫與輸出驗證。

### 中層依賴

這些能力可先做成 reusable packs：

1. `profitability_pack`
2. `growth_pack`
3. `balance_sheet_pack`
4. `cash_flow_pack`
5. `valuation_pack`
6. `insider_pack`
7. `news_sentiment_pack`
8. `price_regime_pack`

### 上層依賴

每位大師只應依賴：

- 自己需要的資料 pack
- 自己的 decision policy
- 自己的 narrative / prompt template

換句話說，**不要讓每位大師直接各自重做底層 API 與指標計算**，而是依賴上面那些共用 packs。

---

## 是否適合分工開發

適合，而且適合按「能力模組」而不是「大師人頭數」分工。

### 不建議的分工方式

- 一人負責一位大師，最後再整合。

問題：

- 會重複做財務抓取與欄位處理。
- 估值函式會長出多份相似版本。
- insider/news/price 分析容易出現不同定義。
- 後期整合成本高。

### 建議的分工方式

#### 工作流 A：底層資料與基礎因子

負責：

- 財務資料 access layer
- line items mapping
- 市值 / 價格 / 新聞 / insider access layer
- 指標正規化與 cache 規格

交付：

- 可被所有大師重用的資料接口

#### 工作流 B：價值投資因子包

負責：

- 財務穩健
- 安全邊際
- owner earnings
- DCF / EV multiple / residual income
- FCF yield / balance sheet stress

可支援：

- Buffett、Graham、Damodaran、Pabrai、Ackman、Burry、Jhunjhunwala

#### 工作流 C：成長與敘事因子包

負責：

- 成長率
- 利潤率趨勢
- PEG / growth-adjusted valuation
- innovation / TAM proxy
- 管理層執行力 proxy

可支援：

- Cathie Wood、Lynch、Fisher、Druckenmiller

#### 工作流 D：事件、情緒與價格風險包

負責：

- insider signals
- news sentiment
- momentum
- volatility regime
- tail risk / convexity

可支援：

- Burry、Munger、Lynch、Fisher、Druckenmiller、Taleb

#### 工作流 E：大師策略與輸出層

負責：

- 每位大師的權重配置
- decision policy
- prompt template
- 回傳 schema

這一層才是大師真正的差異化所在。

---

## 建議的重構藍圖

### 第一階段：先做共用平台

先不要急著把 13 位大師全部重新做完，先建立以下共用抽象：

1. `data_provider`
2. `factor_library`
3. `valuation_library`
4. `sentiment_library`
5. `price_risk_library`
6. `master_agent_base`

### 第二階段：先重做三個代表型大師

建議先選三種差異最大的代表型，驗證抽象是否合理：

1. Buffett：代表價值品質型
2. Cathie Wood 或 Lynch：代表成長敘事型
3. Taleb 或 Druckenmiller：代表價格風險 / 結構型

如果這三個都能落在同一骨架上，其他大師通常可以快速接上。

### 第三階段：批次擴充同族大師

建議順序：

1. Buffett → Munger → Graham → Pabrai
2. Damodaran → Ackman → Burry → Jhunjhunwala
3. Lynch → Fisher → Cathie Wood
4. Druckenmiller → Taleb

這個順序能最大化共用，減少重工。

---

## 最終判斷

### 是否有共同方法

有，而且共同部分很多。共用的不是「投資哲學」，而是：

- 資料抓取
- 基礎指標計算
- 中間分析結構
- signal schema
- agent workflow
- LLM 輸出管線

### 是否都要個別實現

不需要。

應該個別實現的是：

- 每位大師的 decision policy
- 每位大師的指標權重與閾值
- 少數專屬分析函式
- prompt 與最終敘事

不應個別實現的是：

- API 存取
- 財務欄位正規化
- 通用估值元件
- 通用品質 / 成長 / 槓桿 / 情緒 / 價格風險計算
- schema 與工作流程骨架

### 是否有依賴

有，依賴很清楚，而且適合分層：

- 底層資料能力依賴最先完成。
- 中層 factor packs 依賴資料能力。
- 上層大師策略依賴 factor packs。
- risk manager / portfolio manager 再依賴所有大師輸出。

### 是否可以分工開發

可以，而且應該分工。

但建議按 **能力模組** 分工，不要按 **大師名單** 平均拆分，否則最後會做出 13 份高度重複但難整合的實作。

---

## 建議後續產出

如果接下來要正式重構，建議再補三份文件：

1. `factor-library-design.md`：定義可重用因子庫與資料契約。
2. `master-agent-base-design.md`：定義大師代理的共用骨架。
3. `master-agent-implementation-plan.md`：列出每位大師的開發順序、依賴與驗收標準。