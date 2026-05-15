# CLI Batch Terraform

這個目錄只管理 CLI Batch 實驗線的資源：

- Cloud Run Job
- Workflows sequential batch workflow
- Cloud Scheduler
- CLI Batch 專用 service accounts 與 IAM

## 使用方式

1. 準備 tfvars：

```bash
cp deployment/cli_batch/terraform/terraform.tfvars.example deployment/cli_batch/terraform/terraform.tfvars
```

2. 建立或指定 CLI image

```bash
make build-cli-image CLI_IMAGE_TAG=latest
```

預設 image URI:

```bash
asia-east1-docker.pkg.dev/dassa-lab/cli-alpha-council/alpha-council:latest
```

如果你使用不同 repo/tag，可在 deploy 時覆寫 `CLI_IMAGE_URI`

3. 部署：

```bash
make deploy-cli-batch CLI_BATCH_VARS_FILE=terraform.tfvars CLI_IMAGE_TAG=latest
```

4. 銷毀：

```bash
make destroy-cli-batch CLI_BATCH_VARS_FILE=terraform.tfvars CLI_IMAGE_TAG=latest
```

5. 檢查 execution 是否完成：

```bash
make check-cli-execution \
  CLI_EXECUTION_NAME=cli-alpha-council-job-rbn64 \
  CLI_GCS_OBJECT=gs://alphacouncil/tw/2330/2026-05-06/portfolio_report.json
```

## 注意

- 這裡不管理 Agent Service
- `cli_image` 必須是已存在且可被 Cloud Run Job 拉取的容器映像
- Scheduler 會把固定參數送進 Workflow；手動執行 Workflow 時也要提供同樣 shape 的 `argument` JSON
- Workflow 會依序執行每個 ticker，等待該 Cloud Run Job 完成後，再間隔至少 500ms 啟動下一檔
- 單一 ticker 若遇到 Vertex `429 / RESOURCE_EXHAUSTED`，CLI 會自動重試 3 次，等待時間依序為 5、10、15 分鐘
