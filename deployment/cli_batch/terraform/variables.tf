variable "project_id" {
  description = "GCP project ID for CLI batch resources."
  type        = string
  default     = "dassa-lab"
}

variable "region" {
  description = "GCP region for Cloud Run Job, Workflows, and Scheduler."
  type        = string
  default     = "asia-east1"
}

variable "vertex_location" {
  description = "Vertex AI location used by the CLI runtime."
  type        = string
  default     = "us-central1"
}

variable "cli_image" {
  description = "Container image URI for the AlphaCouncil CLI job."
  type        = string
}

variable "bucket_root" {
  description = "GCS root where reports and build logs are stored."
  type        = string
  default     = "gs://alphacouncil"
}

variable "market" {
  description = "Market passed to alpha-council run."
  type        = string
  default     = "tw"

  validation {
    condition     = contains(["tw", "us"], var.market)
    error_message = "market must be tw or us."
  }
}

variable "tickers" {
  description = "Ticker list scheduled for sequential batch execution."
  type        = list(string)
  default = [
    "2330",
    "2308",
    "2454",
    "2317",
    "3711",
    "2383",
    "2345",
    "3037",
    "2303",
    "2382",
    "2881",
    "2891",
    "2882",
    "2886",
    "2327",
  ]

  validation {
    condition     = length(var.tickers) > 0 && alltrue([for ticker in var.tickers : trimspace(ticker) != ""])
    error_message = "tickers must contain at least one non-empty symbol."
  }
}

variable "masters" {
  description = "Comma-separated master selection passed to alpha-council run."
  type        = string
  default     = "1,2,3"
}

variable "report_format" {
  description = "Report format passed to alpha-council run."
  type        = string
  default     = "json"

  validation {
    condition     = contains(["json", "md"], var.report_format)
    error_message = "report_format must be json or md."
  }
}

variable "timeout_seconds" {
  description = "Run timeout passed to alpha-council run and Cloud Run Job task timeout."
  type        = number
  default     = 1800
}

variable "schedule" {
  description = "Cloud Scheduler cron expression."
  type        = string
  default     = "10 16 * * 1-5"
}

variable "time_zone" {
  description = "Cloud Scheduler time zone."
  type        = string
  default     = "Asia/Taipei"
}

variable "job_memory" {
  description = "Memory limit for the Cloud Run Job container."
  type        = string
  default     = "4Gi"
}

variable "job_cpu" {
  description = "CPU limit for the Cloud Run Job container."
  type        = string
  default     = "2"
}

variable "job_task_count" {
  description = "Number of tasks per Cloud Run Job execution."
  type        = number
  default     = 1
}

variable "poll_interval_seconds" {
  description = "Workflow polling interval while waiting for each job execution."
  type        = number
  default     = 10
}

variable "labels" {
  description = "Labels applied to managed resources where supported."
  type        = map(string)
  default = {
    managed-by = "terraform"
    track      = "cli-batch"
  }
}
