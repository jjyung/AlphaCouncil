# 基本面資料模型（Schema）v1 提案

本文件定義 Fundamentals Analyst 的標準化資料模型，目標是：

- 統一 US / TW 多來源欄位
- 區分日 / 月 / 季不同顆粒度，避免資訊失真
- 支援資料落地快取與後續重算

---

## 一、顆粒度原則

不建議把所有資訊強制降到「月」。

建議採多顆粒模型：

- `day`：估值快照（P/E、P/B、殖利率）
- `month`：月營收序列（TW 核心）
- `quarter`：財報衍生指標（ROE、Net Margin、Debt/Equity、FCF）

儲存分區可用「年 / 月」，但每個資料點都要保留 `period_type` 與 `period_end`。

---

## 二、主模型：`FundamentalsBundleV1`

### 2.1 Top-level

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `schema_version` | `str` | Y | 固定 `fundamentals.bundle.v1` |
| `instrument` | `object` | Y | 標的識別資訊 |
| `as_of` | `object` | Y | 本次分析與產出時間 |
| `valuation_snapshot` | `object` | Y | 估值快照（日） |
| `profitability_data` | `object` | Y | 獲利能力（季） |
| `growth_data` | `object` | Y | 成長資料（季 + 月） |
| `financial_health_data` | `object` | Y | 財務健康（季） |
| `signal_summary` | `object` | N | 規則化判讀摘要 |
| `data_quality` | `object` | Y | 缺值、警示、完整度 |
| `lineage` | `object` | Y | 資料來源與 fallback 軌跡 |

### 2.2 `instrument`

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `market` | `"us" | "tw"` | Y | 市場別 |
| `ticker_input` | `str` | Y | 使用者輸入代號 |
| `ticker_canonical` | `str` | Y | 內部主鍵（TW 建議純數字，如 `2330`） |
| `resolved_symbol` | `str` | Y | 實際查詢代號（如 `2330.TW`） |
| `board` | `"listed" | "otc" | "us" | "unknown"` | Y | 掛牌別 |

### 2.3 `as_of`

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `analysis_date` | `str(YYYY-MM-DD)` | Y | 分析基準日 |
| `generated_at` | `str(ISO8601)` | Y | bundle 產生時間 |

### 2.4 `valuation_snapshot`（day）

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `period_type` | `"day"` | Y | 固定日顆粒 |
| `period_end` | `str(YYYY-MM-DD)` | Y | 快照日期 |
| `pe_ratio` | `float | null` | Y | 本益比 |
| `pb_ratio` | `float | null` | Y | 股價淨值比 |
| `dividend_yield_pct` | `float | null` | Y | 現金殖利率（百分比） |
| `source` | `str` | Y | 最終採用來源 |
| `source_confidence` | `"official" | "fallback"` | Y | 來源可信度等級 |

### 2.5 `profitability_data`（quarter）

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `period_type` | `"quarter"` | Y | 固定季顆粒 |
| `period_end` | `str` | Y | 例：`2025-Q4` 或季末日期 |
| `roe_pct` | `float | null` | Y | 股東權益報酬率 |
| `eps` | `float | null` | Y | 每股盈餘 |
| `net_margin_pct` | `float | null` | Y | 淨利率 |
| `source` | `str` | Y | 資料來源 |

### 2.6 `growth_data`（mixed）

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `quarterly` | `object` | Y | 季成長指標 |
| `monthly_revenue_series` | `array` | N | TW 月營收序列 |
| `source` | `str` | Y | 主要來源 |

`quarterly` 子欄位：

- `period_type`: `"quarter"`
- `period_end`: `str`
- `revenue_latest`: `float | null`
- `revenue_qoq_pct`: `float | null`
- `revenue_yoy_pct`: `float | null`

`monthly_revenue_series[]` 子欄位：

- `period_type`: `"month"`
- `period`: `str(YYYY-MM)`
- `revenue`: `float | null`
- `yoy_pct`: `float | null`
- `mom_pct`: `float | null`

### 2.7 `financial_health_data`（quarter）

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `period_type` | `"quarter"` | Y | 固定季顆粒 |
| `period_end` | `str` | Y | 季別 |
| `debt_to_equity` | `float | null` | Y | 負債權益比 |
| `current_ratio` | `float | null` | N | 流動比率 |
| `free_cashflow` | `float | null` | Y | 自由現金流 |
| `operating_cashflow` | `float | null` | Y | 營業現金流 |
| `source` | `str` | Y | 資料來源 |

### 2.8 `data_quality`

- `warnings: list[str]`
- `missing_fields: list[str]`
- `staleness_days: object`（例如 `{"valuation": 1, "profitability": 43}`）

### 2.9 `lineage`

- `sources: list[object]`，每筆至少含：
  - `dataset`（valuation/monthly_revenue/financials）
  - `provider`（twse/tpex/mops/yfinance）
  - `endpoint`（URL 或 API 名稱）
  - `fetched_at`（ISO8601）
  - `raw_file`（raw 快照相對路徑）
- `fallback_chain: list[str]`（例如 `twse -> tpex -> yfinance`）

---

## 三、JSON 範例（節錄）

```json
{
  "schema_version": "fundamentals.bundle.v1",
  "instrument": {
    "market": "tw",
    "ticker_input": "2330",
    "ticker_canonical": "2330",
    "resolved_symbol": "2330.TW",
    "board": "listed"
  },
  "as_of": {
    "analysis_date": "2026-04-15",
    "generated_at": "2026-04-15T09:30:00+08:00"
  },
  "valuation_snapshot": {
    "period_type": "day",
    "period_end": "2026-04-15",
    "pe_ratio": 21.5,
    "pb_ratio": 5.2,
    "dividend_yield_pct": 2.4,
    "source": "twse",
    "source_confidence": "official"
  },
  "growth_data": {
    "quarterly": {
      "period_type": "quarter",
      "period_end": "2025-Q4",
      "revenue_latest": 800000000000.0,
      "revenue_qoq_pct": 3.1,
      "revenue_yoy_pct": 12.4
    },
    "monthly_revenue_series": [
      {
        "period_type": "month",
        "period": "2026-03",
        "revenue": 235000000000.0,
        "yoy_pct": 18.2,
        "mom_pct": -4.8
      }
    ],
    "source": "mops"
  }
}
```

---

## 四、版本策略

- major：欄位語意改動或破壞相容（`v1 -> v2`）
- minor：新增可選欄位（`v1.0 -> v1.1`）
- patch：文件修正、不改結構
