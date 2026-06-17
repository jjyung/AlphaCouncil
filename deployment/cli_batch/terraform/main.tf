terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.31.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  job_name                = "cli-alpha-council-job"
  workflow_name           = "cli-alpha-council-workflow"
  scheduler_name          = "cli-alpha-council-scheduler"
  job_container_name      = "alpha-council-cli"
  job_service_account_id  = "cli-alpha-council-job"
  workflow_service_account_id = "cli-alpha-council-workflow"
  scheduler_service_account_id = "cli-alpha-council-scheduler"
  normalized_tickers      = [for ticker in var.tickers : trimspace(ticker)]
  default_ticker          = local.normalized_tickers[0]
  group_a_bucket_root     = "${var.bucket_root}/value-stable"
  scheduler_argument = {
    tickers         = local.normalized_tickers
    market          = var.market
    masters         = var.masters
    report_format   = var.report_format
    timeout_seconds = tostring(var.timeout_seconds)
  }
}

resource "google_service_account" "cli_batch_job" {
  account_id   = local.job_service_account_id
  display_name = "AlphaCouncil CLI Batch Job"
}

resource "google_service_account" "cli_batch_workflow" {
  account_id   = local.workflow_service_account_id
  display_name = "AlphaCouncil CLI Batch Workflow"
}

resource "google_service_account" "cli_batch_scheduler" {
  account_id   = local.scheduler_service_account_id
  display_name = "AlphaCouncil CLI Batch Scheduler"
}

resource "google_project_iam_member" "cli_batch_job_storage" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.cli_batch_job.email}"
}

resource "google_project_iam_member" "cli_batch_job_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cli_batch_job.email}"
}

resource "google_project_iam_member" "cli_batch_job_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cli_batch_job.email}"
}

resource "google_project_iam_member" "cli_batch_workflow_job_runner" {
  project = var.project_id
  role    = "roles/run.jobsExecutorWithOverrides"
  member  = "serviceAccount:${google_service_account.cli_batch_workflow.email}"
}

resource "google_project_iam_member" "cli_batch_workflow_run_viewer" {
  project = var.project_id
  role    = "roles/run.viewer"
  member  = "serviceAccount:${google_service_account.cli_batch_workflow.email}"
}

resource "google_project_iam_member" "cli_batch_scheduler_workflow_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.cli_batch_scheduler.email}"
}

# ---------------------------------------------------------------------------
# Gemini API key from Secret Manager (replaces Vertex AI auth)
# ---------------------------------------------------------------------------

data "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "alpha-council-gemini-api-key"
}

resource "google_secret_manager_secret_iam_member" "cli_batch_job_secret_access" {
  project  = var.project_id
  secret_id = data.google_secret_manager_secret.gemini_api_key.secret_id
  role     = "roles/secretmanager.secretAccessor"
  member   = "serviceAccount:${google_service_account.cli_batch_job.email}"
}

resource "google_cloud_run_v2_job" "cli_batch" {
  name                = local.job_name
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  template {
    task_count = var.job_task_count

    template {
      max_retries     = 0
      timeout         = format("%ss", var.timeout_seconds)
      service_account = google_service_account.cli_batch_job.email

      containers {
        name    = local.job_container_name
        image   = var.cli_image
        command = ["/code/.venv/bin/alpha-council", "run"]
        args = [
          "--ticker",
          local.default_ticker,
          "--market",
          var.market,
          "--masters",
          var.masters,
          "--report-format",
          var.report_format,
          "--timeout-seconds",
          tostring(var.timeout_seconds),
        ]

        env {
          name  = "ALPHACOUNCIL_PERSIST_ENABLED"
          value = "true"
        }

        env {
          name  = "GCS_BUCKET_ROOT"
          value = local.group_a_bucket_root
        }

        env {
          name  = "GOOGLE_GENAI_USE_VERTEXAI"
          value = "false"
        }

        env {
          name  = "GOOGLE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.gemini_api_key.secret_id
              version = "1"
            }
          }
        }

        env {
          name  = "ALPHACOUNCIL_MODEL"
          value = "gemini-3.1-flash-lite"
        }

        resources {
          limits = {
            cpu    = var.job_cpu
            memory = var.job_memory
          }
        }
      }
    }
  }
}

resource "google_workflows_workflow" "cli_batch" {
  name            = local.workflow_name
  region          = var.region
  description     = "AlphaCouncil CLI batch sequential workflow"
  service_account = google_service_account.cli_batch_workflow.email
  labels          = var.labels

  source_contents = templatefile("${path.module}/workflow.yaml.tftpl", {
    project_id            = var.project_id
    region                = var.region
    job_name              = local.job_name
    job_container_name    = local.job_container_name
    poll_interval_seconds = var.poll_interval_seconds
  })
}

resource "google_cloud_scheduler_job" "cli_batch" {
  name        = local.scheduler_name
  description = "Weekday trigger for AlphaCouncil CLI batch workflow"
  schedule    = var.schedule
  time_zone   = var.time_zone
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/projects/${var.project_id}/locations/${var.region}/workflows/${google_workflows_workflow.cli_batch.name}/executions"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode(jsonencode({
      argument = jsonencode(local.scheduler_argument)
    }))

    oauth_token {
      service_account_email = google_service_account.cli_batch_scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}

# ---------------------------------------------------------------------------
# Group B — 成長創新組 (Growth Innovation)
# Masters: #6 Cathie Wood, #8 Peter Lynch, #9 Phil Fisher
# A/B test variant, shares SAs & IAM with Group A
# ---------------------------------------------------------------------------

locals {
  group_b_name_suffix  = "growth-innovation"
  group_b_job_name     = "cli-alpha-council-job-${local.group_b_name_suffix}"
  group_b_workflow_name = "cli-alpha-council-workflow-${local.group_b_name_suffix}"
  group_b_scheduler_name = "cli-alpha-council-scheduler-${local.group_b_name_suffix}"
  group_b_bucket_root  = "${var.bucket_root}/${local.group_b_name_suffix}"
  group_b_masters      = "6,8,9"
  group_b_scheduler_argument = {
    tickers         = local.normalized_tickers
    market          = var.market
    masters         = local.group_b_masters
    report_format   = var.report_format
    timeout_seconds = tostring(var.timeout_seconds)
  }
}

resource "google_cloud_run_v2_job" "cli_batch_group_b" {
  name                = local.group_b_job_name
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  template {
    task_count = var.job_task_count

    template {
      max_retries     = 0
      timeout         = format("%ss", var.timeout_seconds)
      service_account = google_service_account.cli_batch_job.email

      containers {
        name    = local.job_container_name
        image   = var.cli_image
        command = ["/code/.venv/bin/alpha-council", "run"]
        args = [
          "--ticker",
          local.default_ticker,
          "--market",
          var.market,
          "--masters",
          local.group_b_masters,
          "--report-format",
          var.report_format,
          "--timeout-seconds",
          tostring(var.timeout_seconds),
        ]

        env {
          name  = "ALPHACOUNCIL_PERSIST_ENABLED"
          value = "true"
        }

        env {
          name  = "GCS_BUCKET_ROOT"
          value = local.group_b_bucket_root
        }

        env {
          name  = "ALPHACOUNCIL_MODEL"
          value = "gemini-3.1-flash-lite"
        }

        env {
          name  = "GOOGLE_GENAI_USE_VERTEXAI"
          value = "false"
        }

        env {
          name  = "GOOGLE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.gemini_api_key.secret_id
              version = "1"
            }
          }
        }

        resources {
          limits = {
            cpu    = var.job_cpu
            memory = var.job_memory
          }
        }
      }
    }
  }
}

resource "google_workflows_workflow" "cli_batch_group_b" {
  name            = local.group_b_workflow_name
  region          = var.region
  description     = "AlphaCouncil CLI batch workflow — Group B (成長創新組)"
  service_account = google_service_account.cli_batch_workflow.email
  labels          = var.labels

  source_contents = templatefile("${path.module}/workflow.yaml.tftpl", {
    project_id            = var.project_id
    region                = var.region
    job_name              = local.group_b_job_name
    job_container_name    = local.job_container_name
    poll_interval_seconds = var.poll_interval_seconds
  })
}

resource "google_cloud_scheduler_job" "cli_batch_group_b" {
  name        = local.group_b_scheduler_name
  description = "Weekday trigger for AlphaCouncil CLI batch workflow — Group B (成長創新組)"
  schedule    = var.schedule
  time_zone   = var.time_zone
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/projects/${var.project_id}/locations/${var.region}/workflows/${google_workflows_workflow.cli_batch_group_b.name}/executions"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode(jsonencode({
      argument = jsonencode(local.group_b_scheduler_argument)
    }))

    oauth_token {
      service_account_email = google_service_account.cli_batch_scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}
