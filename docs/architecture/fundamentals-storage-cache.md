# 基本面資料落地與快取策略（提案）

本文件定義 Fundamentals 資料如何落地到專案目錄，目標是避免重複抓取、保留可追溯性，並支援後續重算。

---

## 一、目錄規劃

根目錄：

`alpha_council/data/fundamentals/`

分區規則：

`{market}/{ticker_canonical}/{YYYY}/{MM}/`

範例：

- `alpha_council/data/fundamentals/tw/2330/2026/04/`
- `alpha_council/data/fundamentals/us/AAPL/2026/04/`

---

## 二、每月分區內檔案

### 2.1 `bundle.v1.json`

- 標準化輸出，格式遵循 `docs/data-models/fundamentals-schema.md`
- 供 agent 直接讀取

### 2.2 `manifest.json`

- 快取控制資訊：
  - `schema_version`
  - `created_at` / `updated_at`
  - `coverage`
  - `ttl`
  - `hashes`
  - `last_fetch_status`

### 2.3 `sources/`（raw 快照）

- 保留原始來源回應，便於稽核與除錯
- 檔名建議：`{dataset}.{provider}.{period}.json`

例：

- `sources/valuation.twse.2026-04-15.json`
- `sources/valuation.tpex.2026-04-15.json`
- `sources/monthly_revenue.mops.2026-03.json`
- `sources/financials.mops.2025-Q4.json`
- `sources/info.yfinance.2026-04-15.json`

---

## 三、最小揭露顆粒與存放策略

結論：

- 儲存分區採「年/月」
- 指標本身保留原生顆粒（day/month/quarter）

對應：

- 估值快照：`day`
- 月營收：`month`
- 財報衍生：`quarter`

理由：

- 估值為日快照，降到月會失去時點資訊
- 季報本質是季，不應強制月化
- 月營收正好對齊月分區，利於 TW 報告生成

---

## 四、避免重抓流程（Read-Through Cache）

1. 依 `market/ticker/YYYY/MM` 找 `bundle.v1.json`
2. 讀 `manifest.json`，檢查各資料集 TTL 與 coverage
3. 缺失或過期的資料集才重抓
4. 合併更新 bundle
5. 寫回 `bundle.v1.json`、`manifest.json`、`sources/*`

---

## 五、TTL 建議

| 資料集 | 顆粒 | 建議 TTL |
|--------|------|----------|
| valuation_snapshot | day | 1 天 |
| monthly_revenue | month | 35 天 |
| quarterly_financials | quarter | 100 天 |
| annual_distribution | year | 370 天 |

---

## 六、`manifest.json` 建議欄位

```json
{
  "schema_version": "fundamentals.bundle.v1",
  "created_at": "2026-04-15T09:30:00+08:00",
  "updated_at": "2026-04-15T09:35:00+08:00",
  "coverage": {
    "valuation_period_end": "2026-04-15",
    "monthly_revenue_latest": "2026-03",
    "quarterly_latest": "2025-Q4"
  },
  "ttl": {
    "valuation_snapshot_days": 1,
    "monthly_revenue_days": 35,
    "quarterly_financials_days": 100
  },
  "hashes": {
    "bundle": "sha256:...",
    "sources/valuation.twse.2026-04-15.json": "sha256:..."
  },
  "last_fetch_status": {
    "twse": "ok",
    "mops": "ok",
    "yfinance": "fallback_used"
  }
}
```

---

## 七、實作建議

- 先在 `alpha_council/analysts/fundamental_analyst.py` 加入 `storage layer`（讀寫 bundle/manifest）
- 首版先落地 JSON 檔案，不引入 DB
- 線上版可直接把同一套路徑規則搬到 GCS（object key 沿用 `{market}/{ticker}/{YYYY}/{MM}`）
- 本地檔案與 GCS 共享相同 schema 與命名，僅替換 storage adapter
