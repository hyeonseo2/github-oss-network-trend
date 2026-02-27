provider "google" {
  project = var.project_id
  region  = var.region
}

resource "random_id" "bucket_suffix" {
  byte_length = 3
}

locals {
  name_prefix     = "oss-analytics-${var.environment}"
  raw_bucket_name = "${local.name_prefix}-raw-${random_id.bucket_suffix.hex}"

  service_accounts = {
    dbt = "${local.name_prefix}-dbt-sa"
  }

  iam_roles = [
    "roles/bigquery.jobUser",
    "roles/bigquery.dataViewer",
    "roles/bigquery.dataEditor",
    "roles/storage.objectViewer",
    "roles/storage.objectAdmin"
  ]
}

resource "google_storage_bucket" "raw_data_lake" {
  name                        = local.raw_bucket_name
  location                    = var.region
  force_destroy               = var.bucket_force_destroy
  uniform_bucket_level_access = true

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = var.raw_table_ttl_days
    }
  }

  versioning {
    enabled = true
  }
}

resource "google_bigquery_dataset" "raw" {
  dataset_id                 = var.raw_dataset_id
  location                   = var.region
  delete_contents_on_destroy = false
  default_table_expiration_ms = floor(
    var.raw_table_ttl_days * 24 * 60 * 60 * 1000
  )
}

resource "google_bigquery_dataset" "mart" {
  dataset_id                 = var.mart_dataset_id
  location                   = var.region
  delete_contents_on_destroy = false
}

resource "google_bigquery_table" "raw_github_events" {
  dataset_id = google_bigquery_dataset.raw.dataset_id
  table_id   = var.raw_table_id

  deletion_protection = true

  time_partitioning {
    type          = "DAY"
    field         = "created_at"
    expiration_ms = floor(var.raw_table_ttl_days * 24 * 60 * 60 * 1000)
  }

  clustering = ["repo_name"]

  schema = jsonencode([
    { name = "event_type", type = "STRING", mode = "NULLABLE" },
    { name = "repo_name", type = "STRING", mode = "NULLABLE" },
    { name = "contributor", type = "STRING", mode = "NULLABLE" },
    { name = "created_at", type = "TIMESTAMP", mode = "NULLABLE" }
  ])
}

resource "google_service_account" "workload" {
  for_each     = local.service_accounts
  account_id   = each.value
  display_name = "${upper(each.key)} service account for OSS analytics"
}

locals {
  iam_bindings = flatten([
    for sa_key, sa in google_service_account.workload : [
      for role in local.iam_roles : {
        sa_email = sa.email
        role     = role
      }
    ]
  ])
}

resource "google_project_iam_member" "workload_roles" {
  for_each = {
    for binding in local.iam_bindings :
    "${binding.sa_email}-${binding.role}" => binding
  }

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${each.value.sa_email}"
}

resource "google_bigquery_dataset_iam_member" "raw_dataset_access" {
  for_each = google_service_account.workload

  dataset_id = google_bigquery_dataset.raw.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${each.value.email}"
}

resource "google_bigquery_dataset_iam_member" "mart_dataset_access" {
  for_each = google_service_account.workload

  dataset_id = google_bigquery_dataset.mart.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${each.value.email}"
}

resource "google_storage_bucket_iam_member" "raw_bucket_access" {
  for_each = google_service_account.workload

  bucket = google_storage_bucket.raw_data_lake.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${each.value.email}"
}

