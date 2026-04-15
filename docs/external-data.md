# AlphaCouncil — 外部資料來源說明

## 一、外部 API 概覽

AlphaCouncil 採取雙軌資料架構，依 `market` 欄位（`us` / `tw`）自動路由至對應供應商。

| 類別          | US 軌道                                      | TW 軌道                                   |
| ------------- | -------------------------------------------- | ----------------------------------------- |
| 股價 / K 線   | yfinance                                     | yfinance（ticker 加 `.TW` / `.TWO` suffix） |
| 技術指標      | stockstats（計算自股價資料）                 | stockstats（共用，計算邏輯相同）          |
| 財報 / 基本面 | yfinance                                     | yfinance .TW + TWSE OpenAPI               |
| 新聞          | yfinance Ticker.news                         | 鉅亨網 HTTP GET                           |
| 市場心理      | yfinance（options）+ 波動指數 proxy          | TAIFEX 臺指選擇權波動率指數 + Put/Call Ratio + 市場行為 proxy |
| 籌碼          | yfinance（short interest / holders）         | TWSE / TPEX OpenAPI（融資融券、借券）     |
| 三大法人      | —                                            | TWSE / TPEX OpenAPI（外資、投信、自營商） |

LLM API（Gemini、Claude、OpenAI）由 ADK 原生 / LiteLLM 管理，與金融資料層完全分離。

---

## 二、US 軌道

### 股價：yfinance

```python
import yfinance as yf

ticker = yf.Ticker("AAPL")
hist = ticker.history(start="2026-01-01", end="2026-04-01")
# 回傳 DataFrame：Open, High, Low, Close, Volume
```

- **免費**，無需 API 金鑰
- 涵蓋 OHLCV、股息、股票分割

### 新聞：yfinance Ticker.news

```python
news = ticker.news  # 回傳最近新聞列表（dict[]）
# 欄位：title, publisher, link, providerPublishTime, type
```

- 免費，以英文新聞為主
- 速率限制寬鬆，適合研究用途

### 財報 / 基本面：yfinance

```python
info = ticker.info            # P/E、EPS、市值等摘要
financials = ticker.financials  # 損益表（年度）
balance_sheet = ticker.balance_sheet
cashflow = ticker.cashflow
```

### 市場心理：yfinance

```python
vix = yf.Ticker("^VIX").history(period="3mo")  # VIX 波動率指數
vvix = yf.Ticker("^VVIX").history(period="3mo")  # VVIX（VIX 的波動率）
options = ticker.option_chain(expiry)  # Put/Call ratio 計算來源
```

- US 市場心理分析以 VIX、VVIX、Put/Call Ratio、Options Skew 等數字型風險偏好指標為主
- `short interest` 雖可由 yfinance 取得，但在 AlphaCouncil 規劃中歸屬籌碼分析，不歸市場心理分析

---

## 三、TW 軌道

### 股價：yfinance（.TW suffix）

```python
ticker = yf.Ticker("2330.TW")  # 台積電
hist = ticker.history(start="2026-01-01", end="2026-04-01")
```

- 資料來源為雅虎台股，OHLCV 資料完整
- 上市：`XXXX.TW`，上櫃：`XXXX.TWO`
- 台股 ticker 為四位數字（例如 `2330`），系統會自動補上 `.TW` suffix

### 新聞：鉅亨網（Anue / cnyes.com）

**端點**：`https://news.cnyes.com/api/v3/news/category/tw_stock`

```python
import httpx

def get_tw_news(ticker: str, limit: int = 20) -> list[dict]:
    url = "https://news.cnyes.com/api/v3/news/category/tw_stock"
    params = {"limit": limit, "keyword": ticker}
    resp = httpx.get(url, params=params, timeout=10)
    return resp.json()["items"]["data"]
```

- **免費**，無需 API 金鑰
- 回傳繁體中文新聞，包含標題、摘要、發布時間
- 速率限制：建議請求間隔 ≥ 1 秒

### 財報 / 基本面：TWSE / TPEX OpenAPI + MOPS（TW 官方為主）

台股基本面資料策略以官方來源為主，`yfinance .TW` 僅作備援：

| 資料類型 | 主要來源 | 說明 |
| -------- | -------- | ---- |
| P/E、P/B、現金殖利率（上市） | TWSE OpenAPI `/BWIBBU_ALL` | 官方每日快照，免費免 API Key |
| P/E、P/B、現金殖利率（上櫃） | TPEX OpenAPI | 與 TWSE 口徑一致，官方、免費 |
| 月營收、季報、年報 | MOPS（公開資訊觀測站） | 台股月粒度營收唯一來源，季度財務數字 |
| 備援 | `yfinance .TW` / `.TWO` | 快速 snapshot，非官方 |

```
TWSE OpenAPI Base URL: https://openapi.twse.com.tw/v1
```

| 端點                         | 說明                             | 需要 API 金鑰 |
| ---------------------------- | -------------------------------- | ------------- |
| `/exchangeReport/BWIBBU_ALL` | 所有上市股本益比、殖利率、淨值比 | 否            |
| `/exchangeReport/MI_INDEX`   | 大盤指數資料                     | 否            |
| `/stock/DAY_CAP_*`           | 個股日收盤資訊                   | 否            |

```python
import httpx

def get_tw_pe_yield(ticker: str) -> dict:
    url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
    resp = httpx.get(url, timeout=15)
    data = resp.json()
    return next((d for d in data if d["Code"] == ticker), {})
```

**MOPS** 是台灣上市櫃公司財報的法定公告平台，月營收（每月 10 日前公布）為台股特有且不可替代的領先指標，`yfinance` 無法提供月粒度資料。

### 籌碼：TWSE OpenAPI（融資融券）

```
端點: https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN
```

回傳欄位：`FujiaqidaiBuyingAmount`（融資買進）、`FujiaqidaiSellingAmount`（融資賣出）等。

### 大盤籌碼：TAIFEX

- 三大法人期貨部位：`/cht/3/futContractsDate` 與下載頁 `futContractsDateDown`
- 外資期貨未平倉：由三大法人期貨資料篩出 `外資` 後取得多方 / 空方 / 淨額
- 選擇權大額交易人未沖銷部位：`/cht/3/largeTraderOptQry` 與下載頁 `largeTraderOptDown`
- 全市場 Put/Call 比：`/cht/3/pcRatio` 與下載頁 `pcRatioDown`

- 上述資料適合用來判讀**大盤全局方向與大戶衍生品部位**
- 不建議直接把外資期貨未平倉或大額交易人選擇權 PCR 套用為單一個股買進訊號

### 個股籌碼：TWSE / TPEX 現貨與權證

- 三大法人現貨買賣超：TWSE / TPEX 官方資料
- 融資融券與借券：TWSE / TPEX 官方資料
- 權證資料：建議作為短線交易壓力輔助訊號

- 個股籌碼主看法人現貨進出，不看分點資訊
- 權證若買入或活躍度明顯升高，需提示可能存在隔日沖賣壓

### 市場心理：TAIFEX 波動率指數 + Put/Call Ratio + 市場行為 proxy

台股有免費官方波動率指標可用，以 TAIFEX 提供的臺指選擇權波動率指數（台版 VIX）與 Put/Call Ratio 為核心。

#### 臺指選擇權波動率指數（台版 VIX）

```
即時/分鐘資料: https://www.taifex.com.tw/cht/7/vixMinNew
每日歷史資料: https://www.taifex.com.tw/cht/7/vixDaily3MNew
```

- TAIFEX 以 CBOE VIX 公式計算，反映台指選擇權隱含波動率
- 免費、官方、無需 API 金鑰
- 此為 Psychology Analyst 的首要核心指標

#### 臺指選擇權 Put/Call Ratio

```
端點: https://www.taifex.com.tw/cht/3/pcRatio
下載頁: https://www.taifex.com.tw/cht/3/pcRatioDown
```

- 提供成交量口徑與未平倉量（OI）口徑兩種 Put/Call 比
- 成交量口徑反映交易情緒，OI 口徑反映持有偏好
- 免費、官方、無需 API 金鑰

> 注意：此 PCR 同時被 Chip Analyst 引用作為大額交易人 PCR 的對照基準線，用途不同。Psychology Analyst 用於整體市場情緒判讀。

#### 匯率 proxy

- USD/TWD 匯率趨勢：透過 `yfinance` 取得 `USDTWD=X`
- 定位為資金流向的間接觀測，不算籌碼核心

#### 市場行為 proxy（數字型）

以加權指數（`^TWII`，yfinance）與 TWSE 每日市場統計為基礎計算：

- 加權指數近 5 日實現波動率
- MA5 乖離率
- 上漲/下跌家數比（TWSE `/exchangeReport/MI_INDEX`）
- 漲停/跌停家數（TWSE `/exchangeReport/MI_INDEX`）
- 跳空缺口頻率
- 近 5 日正負報酬交替次數

這些指標定位為 secondary proxy，輔助核心波動與選擇權指標。

- Psychology Analyst 不使用新聞風險語氣或社群情緒作為心理指標（該部分由 News Analyst 負責）

### 三大法人：TWSE OpenAPI

```
端點: https://openapi.twse.com.tw/v1/exchangeReport/T86
```

欄位：外資買賣超（`Foreign_Difference`）、投信（`Investment_Trust_Difference`）、自營商（`Dealer_Difference`）。

```python
def get_tw_institutional(ticker: str, date: str) -> dict:
    url = "https://openapi.twse.com.tw/v1/exchangeReport/T86"
    resp = httpx.get(url, timeout=15)
    data = resp.json()
    return next((d for d in data if d["Code"] == ticker), {})
```

- **免費**，無需 API 金鑰
- 資料為當日，歷史資料需自行儲存

---

## 四、快取機制

為避免單次 pipeline 執行中重複呼叫相同 API，`tools/cache.py` 實作記憶體內快取：

```python
# tools/cache.py
class Cache:
    _store: dict[str, Any] = {}

    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...

    @classmethod
    def make_key(cls, func_name: str, **kwargs) -> str:
        return f"{func_name}:{json.dumps(kwargs, sort_keys=True)}"
```

快取 key 由 `函式名稱 + 參數組合` 構成，僅在單次執行的生命週期內有效（記憶體快取，不持久化）。

---

## 五、速率限制與重試

| 資料源       | 速率限制           | 重試策略                       |
| ------------ | ------------------ | ------------------------------ |
| yfinance     | 寬鬆（非官方 API） | 失敗時等待 5 秒重試，最多 3 次 |
| 鉅亨網       | 建議間隔 ≥ 1 秒    | 失敗時等待 3 秒重試，最多 2 次 |
| TWSE OpenAPI | 官方 API，速率寬鬆 | 失敗時等待 5 秒重試，最多 2 次 |

---

## 六、環境變數

金融資料層**不需要任何 API 金鑰**（yfinance、鉅亨網、TWSE 均為免費公開資源）。

僅 LLM 需要金鑰，於 `.env` 設定：

```env
# 至少需要其中一個
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```
