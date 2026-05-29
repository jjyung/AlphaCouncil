# ADR-0002: Telegram Bot Short-Lived Interactive Sessions

- Status: Proposed
- Date: 2026-05-08

## Context

專案目前已有兩個可重用的執行面：

- FastAPI 入口：可承接外部 webhook / HTTP 請求
- ADK pipeline：已支援兩階段互動流程，先輸入股票，再等待使用者選擇投資大師

Telegram 整合的產品目標已明確為：

- 互動式 bot
- 僅支援私聊
- 不提供一般聊天對話
- 只接受任務型輸入
- 最終只回傳分析摘要，不回傳完整長篇報告
- 單次分析過程中，允許使用者在第二輪輸入 master 選擇

目前既有 agent state 已包含：

- `awaiting_master_choice`
- `selected_masters`
- `ticker`
- `market`

因此 Telegram 設計的核心問題不是是否需要 session，而是：

- session 應存在多久
- 如何判斷下一則訊息是新股票分析，還是上一輪分析的 master 選擇
- 如何避免 bot 變成長期對話狀態機

## Decision

採用「一檔股票 = 一次短生命週期互動 session」的 Telegram 整合模型。

具體決策如下：

1. Telegram 採用 webhook 模式整合至既有 FastAPI 服務。
2. 每次收到新的股票代碼時，建立一筆新的 bot session 與對應的 ADK session。
3. bot session 只在以下期間存活：
   - 等待使用者選擇 master
   - 分析流程執行中
4. 分析完成、失敗、逾時或使用者取消後，立即刪除該 session，不保留對話上下文。
5. Telegram bot 僅支援任務型互動，不支援自由對話或長期 conversational memory。
6. 輸出格式以摘要為主，Telegram 不承載完整報告本文。
7. session 路由規則如下：
   - `IDLE`：將訊息視為新股票輸入
   - `AWAITING_MASTER`：將訊息視為 master 選擇輸入
   - `RUNNING`：拒絕新任務，提示目前分析進行中
8. 若 bot 正在 `AWAITING_MASTER`，但使用者送來看似新的股票代碼，不直接覆蓋原 session；應提示使用者先完成 master 選擇，或使用 `/cancel` 結束當前流程。
9. 多實例或正式環境不得依賴 in-memory session 作為唯一狀態來源；需使用外部 session store。
10. Telegram 權限模型先限制為單一私聊使用者，以 env 輸入 bot token 與 allowed user id 控制。

## Session Model

Telegram bot 需維護一層獨立於 ADK 的 bot session state，至少包含：

- `telegram_user_id`
- `status`: `idle | awaiting_master | running`
- `ticker`
- `market`
- `adk_session_id`
- `created_at`
- `expires_at`

ADK session state 則延續既有 pipeline 設計，例如：

- `awaiting_master_choice`
- `selected_masters`
- `ticker`
- `market`
- `analysis_intent`

兩層 state 的責任分離如下：

- bot session state：決定 Telegram 訊息該如何路由
- ADK session state：決定 agent pipeline 該如何續跑

## Interaction Rules

標準互動流程如下：

1. 使用者傳入股票代碼
2. bot 建立新 session，啟動第一輪 pipeline
3. 若 pipeline 進入 `awaiting_master_choice=True`，bot 回傳 master 選單並保留 session
4. 使用者回覆 master 編號、`0`、`跳過` 或隨機選擇關鍵字
5. bot 使用同一個 ADK session 繼續執行分析
6. 分析完成後，回傳摘要結果
7. 立即銷毀 session

例外流程如下：

- `AWAITING_MASTER` 逾時：銷毀 session，要求重新輸入股票
- `RUNNING` 中再次輸入內容：提示目前分析進行中
- 使用者輸入 `/cancel`：中止並銷毀 session
- 非 allowed user id：直接拒絕

## Output Policy

Telegram 只回傳摘要，不回傳完整最終報告。建議摘要至少包含：

- 股票與市場
- 最終決策：買入 / 持有 / 賣出
- 建議倉位
- 主要理由摘要
- 風險提醒
- 本輪選擇的大師名單

完整報告若需保留，應透過既有持久化機制落檔，不以 Telegram 長訊息承載。

## Consequences

正面：

- session 邊界清楚，符合任務型 bot，而非聊天型 bot
- 可直接重用既有 `awaiting_master_choice` 流程
- 完成後立即結束上下文，降低狀態污染與維護成本
- 私聊單用戶模型簡化權限與 UX 設計
- 摘要輸出更適合 Telegram 使用情境

負面：

- 使用者在等待 master 時無法直接切換到另一檔股票，需先取消或完成當前流程
- 需額外實作 bot session store，而不能只依賴 ADK state
- 多實例或正式環境需要外部儲存，增加基礎設施需求
- 若未提供完整報告連結，Telegram 端可讀資訊會較受限

## Alternatives Considered

- 長生命週期 chat session
  - 未採用，因需求不是聊天助理，而是單次任務型分析工具

- 無 session 設計，要求第一次訊息就提供 ticker 與 masters
  - 未採用，因既有 pipeline 已支援二階段 master 選擇，強行改成單輪輸入會降低互動性

- 在 `AWAITING_MASTER` 時，自動把看似新 ticker 的訊息視為新任務並覆蓋舊 session
  - 未採用，因容易誤判並造成流程混亂，使用者也難以理解當前狀態

- 採用 Telegram long polling
  - 未採用，因既有系統已有 FastAPI 入口，webhook 模式更符合目前互動設計

- Telegram 回傳完整分析長文
  - 未採用，因 Telegram 不適合承載長篇多段報告，摘要更符合使用情境

## Notes

實作時應一併定義以下環境變數：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_SESSION_TTL_SECONDS`

正式環境建議：

- webhook 驗證 `X-Telegram-Bot-Api-Secret-Token`
- 使用外部 session store（例如 Firestore 或 Redis）
- 對 Telegram update 做基本去重與重送防護

本 ADR 僅定義 Telegram 私聊互動模式與 session lifecycle，不涵蓋：

- 多使用者 / 群組支援
- 排程推播
- 完整報告下載體驗
- 更廣義的 conversational interface
