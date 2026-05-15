# CLI Batch Experiment Deployment

本文件定義 CLI 實驗部署（非主線服務）做法，與 Agent Service 分離。

Agent Service 部署請看 `docs/deployment/agent-service.md`。本文件只涵蓋 CLI Batch。

## 1) 實驗目標

- 固定時間觸發分析
- 一次傳入多個股票代號，依序執行
- 結果寫入 GCS，累積 n 天資料供回測

## 2) 固定參數（目前決議）

- project: `dassa-lab`
- region: `asia-east1`
- vertex model location: `us-central1`
- schedule: `10 16 * * 1-5`
- timezone: `Asia/Taipei`
- bucket root: `gs://alphacouncil`
- masters: `1,2,3`
- report format: `json`
- timeout seconds: `1800`
- tickers:
  - `2330,2308,2454,2317,3711,2383,2345,3037,2303,2382,2881,2891,2882,2886,2327`

## 3) 執行拓樸

- Cloud Scheduler：定時觸發
- Cloud Workflows：逐檔執行與等待完成（多 ticker，負責啟動 jobs）
- Cloud Run Job：執行 `alpha-council run`
- GCS：持久化報告

Cloud Run Job 使用專用 batch image，入口為 `Dockerfile.cli`。

## 4) CLI 介面對齊原則

完全沿用現有 CLI 參數，不新增 deployment 專用 flag：

- `--ticker`
- `--market`
- `--masters`
- `--report-format`
- `--timeout-seconds`

Job 透過 env 控制持久化：

- `ALPHACOUNCIL_PERSIST_ENABLED=true`
- `GCS_BUCKET_ROOT=gs://alphacouncil`
- `GOOGLE_GENAI_USE_VERTEXAI=true`
- `GOOGLE_CLOUD_PROJECT=dassa-lab`
- `GOOGLE_CLOUD_LOCATION=us-central1`

## 5) 權限與安全

Job service account 建議最小權限：

- `roles/storage.objectCreator`
- `roles/logging.logWriter`
- `roles/aiplatform.user`

Workflow/Scheduler 僅授予觸發所需權限，不使用廣域管理角色。

## 6) VPC-SC 注意事項

若組織有 VPC Service Controls，Cloud Build 可能因預設 logs bucket 跨 perimeter 被擋。

建議固定使用：

`--gcs-log-dir=gs://alphacouncil/cloudbuild-logs`

## 7) 清理策略

- Terraform destroy：只刪 Terraform 管理資源（Job/Workflow/Scheduler/SA/IAM）
- 非 Terraform 殘留需另清：
  - GCS reports
  - Cloud Build logs
  - Artifact Registry repository/image

Makefile 已保留對應入口，Terraform root 在 `deployment/cli_batch/terraform`：

- `make deploy-cli-batch`
- `make destroy-cli-batch`
- `make cleanup-gcs-reports`
- `make cleanup-cloudbuild-logs`
- `make cleanup-artifact-repo`

建議先複製：

```bash
cp deployment/cli_batch/terraform/terraform.tfvars.example \
  deployment/cli_batch/terraform/terraform.tfvars
```

然後執行：

```bash
make build-cli-image CLI_IMAGE_TAG=latest
make deploy-cli-batch CLI_BATCH_VARS_FILE=terraform.tfvars CLI_IMAGE_TAG=latest
```

目前 Workflow 會依序處理每個 ticker，等待前一檔 Cloud Run Job 完成後，再間隔至少 500ms 啟動下一檔。

單一 ticker 若遇到 Vertex `429 / RESOURCE_EXHAUSTED`，CLI 會自動重試 3 次，等待時間依序為 5、10、15 分鐘；其他錯誤不重試。

Workflow 完成代表整批 ticker 都已跑完，回傳 payload 會包含每檔 ticker 的成功/失敗摘要。若某一檔失敗，Workflow 仍會繼續執行後續 ticker，最終由 summary 彙整結果。

建議用 execution completion checker 驗證單次執行：

```bash
make check-cli-execution \
  CLI_EXECUTION_NAME=cli-alpha-council-job-rbn64 \
  CLI_GCS_OBJECT=gs://alphacouncil/tw/2330/2026-05-06/portfolio_report.json
```

exit code 約定：

- `0`: execution 已完成，且若指定 GCS 物件則檔案存在
- `1`: execution 已失敗
- `2`: execution 成功，但指定的 GCS 物件不存在
- `3`: execution 仍在進行中

## 8) 實驗分支策略

- 建議在實驗分支執行與驗證
- 不直接影響 main runtime path
- 驗證穩定後再挑選可產品化部分回主線
