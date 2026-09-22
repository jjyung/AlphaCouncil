# 新聞分析師 (News Analyst) 開發方式

## 文件目的

本文件依目前 `alpha_council/analysts/news_analyst.py` 的實作，說明新聞分析師的資料流程、快取、連結驗證與報告規格。

新聞分析師的輸出是可追溯的 `news_report`，不是即時新聞終端，也不直接產生買賣決策。文件中的「目前支援」以程式碼現況為準；未來若增加美股新聞流程，需同步更新本文件、工具介面與測試。

## 一、角色定位

新聞分析師負責從公開新聞來源取得候選文章，確認文章連結狀態，再以保守語氣整理標的新聞、產業外溢與宏觀背景，供研究員、大師與後續決策階段使用。

### 主要職責

- 依股票代號抓取台股新聞候選清單
- 記錄各新聞來源的成功或錯誤狀態
- 以標題去除跨來源重複新聞
- 驗證文章連結，標示失效、軟 404 或未知狀態
- 將新聞分為直接相關、產業關聯、泛財經／宏觀
- 以本次工具回傳的資料產出可核對的 `news_report`

### 不負責事項

- 不自行搜尋或補入工具回傳 JSON 以外的新聞
- 不把抓取日期當成文章發布日期
- 不解讀 MA、RSI、MACD 等技術指標
- 不分析財報、估值、法人流向、融資融券或選擇權指標
- 不直接產生買入、持有或賣出決策

### 目前支援範圍

| 項目 | 現況 |
|------|------|
| 支援市場 | `TW`；其他市場會提早回傳空文章清單 |
| 預設市場 | `TW` |
| 預設日期 | `Asia/Taipei` 時區的當日，格式 `YYYY-MM-DD` |
| 工具 | `get_news(ticker, date, market, validate_links)` |
| Agent 名稱 | `news_analyst` |
| Agent 輸出鍵 | `news_report` |

總覽文件中曾描述 US / TW 雙市場新聞，但目前這個 Agent 的程式實作只有 TW 路徑；`market != "TW"` 時不會改用 `yfinance.Ticker.news`。

## 二、輸入與輸出介面

### `get_news` 輸入

| 參數 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `ticker` | `str` | 必填 | 股票代號，例如 `2330` 或 `2330.TW` |
| `date` | `str` | `""` | 查詢／快取分區日期；空值時使用台灣時區今日 |
| `market` | `str` | `""` | 空值時設為 `TW`；目前只接受 `TW` 的新聞抓取流程 |
| `validate_links` | `bool` | `True` | 是否對每個非空連結做 HEAD → GET 驗證 |

環境變數 `NEWS_VALIDATE_LINKS` 設為 `0`、`false` 或 `no` 時，會全域關閉連結驗證，即使呼叫端傳入 `validate_links=True` 也一樣。這適合離線測試或不希望承受外部網站請求的情境。

### 回傳 JSON

`get_news` 回傳 JSON 字串，不是 Python list。主要欄位如下：

| 欄位 | 說明 |
|------|------|
| `ticker` / `date` / `market` | 本次查詢上下文 |
| `source_status` | 各來源的 `ok (...)` 或 `error: ...` 狀態 |
| `link_validation` | `validated`、`ok`、`broken`、`soft404`、`unknown`、`skipped` 統計 |
| `total_articles` | 去重後的文章總數；快取命中時為快取文章數 |
| `articles` | 最多回傳 30 筆文章物件 |
| `raw_file` | 完整原始資料的本地 JSON 路徑 |
| `cache_hit` | 僅快取命中時加入，值為 `true` |

每筆 `articles[]` 可能包含：

| 欄位 | 說明 |
|------|------|
| `title` | 原始標題 |
| `link` | 原始文章連結，可為空字串 |
| `published` | 來源提供的發布時間，可為空字串 |
| `summary` | 來源提供的摘要，可為空字串 |
| `source` | `經濟日報`、`Yahoo Finance TW` 或 `鉅亨網` |
| `link_status` | `ok`、`unknown`、`broken` 或 `skipped` |
| `link_validation_note` | 連結驗證補充資訊；不是每筆都有 |

`soft404` 在原始 `link_validation` 統計中保留為 `soft404`，但對文章物件的 `link_status` 會正規化為 `broken`，讓 Agent 將其排除於主要新聞清單。

## 三、新聞來源與抓取策略

目前三個來源依序執行；單一來源失敗會記錄錯誤並繼續處理其他來源。

### 3.1 經濟日報 RSS

程式會依序嘗試四個 RSS URL，遇到第一個有 entries 的 feed 即停止嘗試後續候選。來源狀態欄位為 `經濟日報_RSS`。

抓取與篩選規則：

- 先取該 feed 前 20 筆
- 若標題包含清理後的 ticker 或原始 ticker，保留符合項目
- 若沒有符合項目，改用前 10 筆作為背景候選
- 每筆來源固定標記為 `經濟日報`
- 所有候選 RSS 都沒有 entries 時，記錄 error，不宣稱來源成功但有 0 筆

### 3.2 Yahoo Finance Taiwan RSS

來源 URL 為 `https://tw.news.yahoo.com/rss/finance`，來源狀態欄位為 `Yahoo_Finance_TW_RSS`。

抓取與篩選規則：

- 讀取 feed 前 30 筆
- 優先保留標題含 ticker 的項目
- 若沒有符合項目，使用最多 10 筆 fallback 背景新聞
- 每筆來源固定標記為 `Yahoo Finance TW`

### 3.3 鉅亨網 HTML

程式以 ticker 組成以下查詢 URL，並使用瀏覽器 User-Agent 發出請求：

```text
https://news.cnyes.com/news/cat/tw_stock_news?keyword={ticker}
```

抓取與篩選規則：

- 解析 `a[href*='/news/id/']` 連結
- 最多讀取前 20 個候選連結
- 相對連結補上 `https://news.cnyes.com`
- 先按標題去除來源內重複，再最多保留 15 筆
- `published` 與 `summary` 目前通常為空字串
- 來源狀態欄位為 `鉅亨網_HTML`

### 3.4 去重

三個來源合併後，程式以 `title` 做跨來源去重，保留較早加入的那筆，因此來源執行順序會影響同標題文章最後保留的來源。新聞標題為空時不會被一般重複標題規則移除，應由報告層避免把它當成有意義的新聞引用。

## 四、快取與檔案落地

### 4.1 路徑

資料根目錄由程式以 `news_analyst.py` 所在位置推導，與目前工作目錄無關：

```text
alpha_council/data/news/{normalized_ticker}_{date}/news_raw.json
```

`normalized_ticker` 會把非英數字元替換成 `_`，再移除首尾 `_`。例如：

```text
2330.TW -> 2330_TW
AAPL    -> AAPL
```

### 4.2 快取命中條件

讀取既有 `news_raw.json` 前，程式會確認：

- JSON 可解析
- 存在 `ticker`、`date`、`market`、`source_status`、`articles`、`link_validation`、`validate_links`
- `date` 與本次請求完全相同
- `market` 不分大小寫相同
- ticker 比對時忽略結尾 `.TW`
- 若本次要求驗證連結，快取也必須是以 `validate_links=True` 建立

若快取不符合條件，程式重新抓取並覆寫同一分區的 `news_raw.json`。若本次不要求驗證，已驗證或未驗證的快取都可重用。

### 4.3 原始資料與模型摘要

- `news_raw.json` 保存完整去重後文章清單與來源狀態
- 回傳給模型的 `articles` 最多 30 筆，以控制上下文長度
- 非 TW 市場也會建立快取檔，但 `articles` 為空，並在 `source_status.market` 說明目前僅支援 TW
- 快取命中時，回傳 JSON 會額外帶有 `cache_hit: true`

## 五、連結驗證

連結驗證由 `_check_link` 執行，結果會在同一次 `get_news` 呼叫內以 URL 做 memoization，避免同一連結重複請求。

### 驗證順序

1. 先以 `HEAD` 並允許 redirect。
2. `404` 或 `410` 立即標記 `broken`。
3. HEAD 回傳 `200` 時仍會繼續 GET 以檢查軟 404；回傳 `405` 或 HEAD 發生請求例外時也會繼續 GET。
4. HEAD 回傳其他狀態時直接標記 `unknown`，不再發出 GET。
5. 用 `GET`、`stream=True` 讀取最多 64 KiB response body。
6. HTTP 200 且命中軟 404 關鍵字時標記 `soft404`；HTTP 200 且未命中時標記 `ok`。
7. GET 的其他 HTTP 狀態或請求例外標記 `unknown`。

單一連結的 timeout 預設為 8 秒；新聞抓取本身使用的鉅亨網請求 timeout 為 10 秒。驗證請求會帶瀏覽器 User-Agent，以降低被來源網站直接拒絕的機率。

### 狀態與報告處置

| 狀態 | 意義 | `news_report` 處置 |
|------|------|--------------------|
| `ok` | 可取得且未命中軟 404 | 可列入主要新聞清單 |
| `unknown` | 無法確定連結是否可用 | 可列入，但必須註明「連結狀態未知」 |
| `broken` | HTTP 404/410 或軟 404 正規化結果 | 不列入 A/B 主清單，於資料限制統計 |
| `skipped` | 空連結，或全域關閉驗證 | 預設不列入主清單 |

## 六、Agent 行為與報告規格

`news_analyst` 使用 `get_news` 作為唯一工具，`output_key` 為 `news_report`。只要使用者訊息能辨識出單一股票代號，Agent 必須先呼叫工具；未提供日期或市場時傳入空字串，讓工具套用預設值。只有 ticker 缺漏、無法解析，或一次提到多個且意圖不明時才可追問。

### 證據與防幻覺規則

- 只能使用本次 `get_news` 回傳 JSON，不得混入歷史回合、記憶或其他 ticker/date 的新聞
- 每個引用的 `title`、`link`、`published`、`source` 必須逐字保留
- 不得捏造摘要、時間、數字、事件、來源或連結
- `published` 為空時顯示「發布時間：未提供（來源未附時間）」
- 查詢 `date` 是抓取基準日，不可冒充文章發布日
- 所有影響描述採「可能、或、尚待確認、潛在」等保守措辭

### 分類上限

| 分類 | 判定原則 | 上限 |
|------|----------|------|
| A. 標的新聞（Direct） | 標題或摘要明確以目標標的為主要敘事主體 | 3 則 |
| B. 產業關聯 | 影響標的所處產業，但未直接以標的為主體 | 3 則 |
| B-2. 泛財經／宏觀 | 地緣政治、油價、匯率、總體市場等背景 | 2 則 |

若沒有直接相關新聞，必須明確寫出「本次抓取無直接點名標的之報導」，並在影響評估中說明直接關聯有限、可信度較低。

### 固定輸出結構

```markdown
### 新聞分析師報告

本次抓取直接相關：X 則；產業關聯：Y 則；泛財經：Z 則

**A. 標的新聞（Direct）**
**B. 產業與外溢（Indirect）**
**C. 對標的之影響評估（保守）**
**D. 新聞情緒（僅針對本次列表）**
**E. 資料限制**
```

各新聞條目必須包含原始標題、來源、連結與發布時間。C 段分為可能利多、情緒中性、可能利空，並為每個判斷附上已列出新聞的原始標題作為證據。D 段只能選擇：正面、中性偏正、中性、中性偏負、負面。

E 段必須包含：

- `source_status` 各來源摘要
- `link_validation` 各狀態統計
- 被排除的 `broken + soft404` 數量
- `unknown` 條目數量與實際處置
- RSS / HTML 快照不保證涵蓋完整當日事件的限制
- `published` 缺失情況

## 七、在分析師流水線中的位置

新聞分析師被放在 `agent.py` 的 `analyst_team` `ParallelAgent` 中，與技術、心理、基本面及籌碼分析師並行執行：

```text
analyst_team
├── technical_analyst    -> technical_report
├── news_analyst         -> news_report
├── psychology_analyst   -> psychology_report
├── fundamental_analyst  -> fundamentals_report
└── chip_analyst         -> chip_report
```

後續研究員與大師層透過 `news_report` 取得事件與敘事證據；新聞分析師不應重複產出其他分析師負責的數值指標。新聞報告與共用資料快照、基本面、技術面及市場心理報告一起提供下游整合。

## 八、維護與驗證重點

修改新聞流程時，至少應驗證以下情境：

- 空 `date` / `market` 是否仍套用台灣時區與 `TW` 預設
- 非 TW 市場是否回傳明確的 unsupported status 與空文章清單
- 同 ticker、日期、market 的快取是否命中；日期、market 或驗證模式變更時是否重新抓取
- `validate_links=True` 與 `NEWS_VALIDATE_LINKS=0` 的統計是否一致
- HTTP 404、軟 404、未知狀態、空連結是否被正確分類
- 三個來源的同標題新聞是否只保留一筆
- Agent 報告是否遵守文章數量上限、原始欄位逐字引用與 A=0 的聲明

若新增來源，需同步處理來源狀態鍵、文章欄位標準化、跨來源去重、連結驗證、快取回放與 `news_report` 的證據規則。

## 參考文件

- [分析師層總覽](./README.md)
- [技術分析師開發方式](./technical-analyst.md)
- [市場心理分析師開發方式](./psychology-analyst.md)
- [籌碼分析師開發方式](./chip-analyst.md)
- [基本面分析師開發方式](./fundamentals-analyst.md)
- [AlphaCouncil 外部資料來源說明](../external-data.md)
