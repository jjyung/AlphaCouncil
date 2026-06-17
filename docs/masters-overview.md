# Masters Overview — AlphaCouncil

All 13 masters, categorized by investment philosophy into recommended groups for A/B testing.

---

## 完整大師列表

| # | 大師 | 代號 | 核心理念 |
|---|---|---|---|
| 1 | Warren Buffett | `warren_buffett` | 護城河 + 長期複利，重視可預測現金流與管理層紀律 |
| 2 | Ben Graham | `ben_graham` | 深度價值與安全邊際，偏好低估且下檔受保護標的 |
| 3 | Charlie Munger | `charlie_munger` | 高品質企業合理價，強調心智模型與長期競爭優勢 |
| 4 | Aswath Damodaran | `aswath_damodaran` | 估值導向，先釐清敘事再回到現金流與折現假設 |
| 5 | Bill Ackman | `bill_ackman` | 高信念集中投資，催化劑與管理改善是關鍵 |
| 6 | Cathie Wood | `cathie_wood` | 顛覆式創新成長，押注長期技術曲線與平台效應 |
| 7 | Michael Burry | `michael_burry` | 逆向與錯價修正，偏好不對稱風險報酬機會 |
| 8 | Peter Lynch | `peter_lynch` | 由生活洞察找成長，重視業務可理解與基本面驗證 |
| 9 | Phil Fisher | `phil_fisher` | Scuttlebutt 深度研究，聚焦成長品質與管理層執行力 |
| 10 | Mohnish Pabrai | `mohnish_pabrai` | 低風險高不對稱，複製優秀策略並保持耐心 |
| 11 | Stanley Druckenmiller | `stanley_druckenmiller` | 宏觀趨勢 + 風險動態調整，重視時機與部位管理 |
| 12 | Rakesh Jhunjhunwala | `rakesh_jhunjhunwala` | 成長與價值並重，敢於集中於高 conviction 標的 |
| 13 | Nassim Taleb | `nassim_taleb` | 反脆弱與尾部風險，避免脆弱曝險並追求非對稱性 |

---

## AB Testing 分組

### `value-stable` — 價值穩健組（對照組）

| # | 大師 | 角色 |
|---|---|---|
| 1 | Warren Buffett | 護城河與長期複利觀點 |
| 2 | Ben Graham | 安全邊際與深度價值判斷 |
| 3 | Charlie Munger | 高品質企業與心智模型分析 |

**GCS 路徑：** `gs://lighthouse-485801-alpha-council-reports/value-stable/`

### `growth-innovation` — 成長創新組（實驗組）

| # | 大師 | 角色 |
|---|---|---|
| 6 | Cathie Wood | 顛覆式創新與長期技術曲線 |
| 8 | Peter Lynch | 生活選股與基本面成長驗證 |
| 9 | Phil Fisher | Scuttlebutt 成長品質深度研究 |

**GCS 路徑：** `gs://lighthouse-485801-alpha-council-reports/growth-innovation/`

---

## 其他可用分組

這些組別可以用於後續擴充 AB test：

| Group ID | 組名 | 大師 | 風格 |
|---|---|---|---|
| `macro-risk` | 宏觀風險組 | #7 Burry, #11 Druckenmiller, #13 Taleb | 逆向錯價、宏觀趨勢、反脆弱 |
| `valuation-discipline` | 估值紀律組 | #4 Damodaran, #5 Ackman, #10 Pabrai | 估值敘事、高信念集中、不對稱 |
