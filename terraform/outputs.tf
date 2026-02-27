output "raw_bucket_name" {
  value       = google_storage_bucket.raw_data_lake.name
  description = "Raw data lake bucket"
}

output "raw_dataset_id" {
  value       = google_bigquery_dataset.raw.dataset_id
  description = "Raw dataset ID"
}

output "mart_dataset_id" {
  value       = google_bigquery_dataset.mart.dataset_id
  description = "Mart dataset ID"
}

output "raw_table_id" {
  value       = google_bigquery_table.raw_github_events.table_id
  description = "Raw table ID"
}

output "service_accounts" {
  value = {
    for k, sa in google_service_account.workload : k => sa.email
  }
  description = "Workload service account emails"
}
