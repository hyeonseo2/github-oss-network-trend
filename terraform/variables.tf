variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "asia-northeast3"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "raw_dataset_id" {
  description = "BigQuery raw dataset ID"
  type        = string
  default     = "oss_analytics_raw"
}

variable "mart_dataset_id" {
  description = "BigQuery mart dataset ID"
  type        = string
  default     = "oss_analytics_mart"
}

variable "raw_table_id" {
  description = "BigQuery raw table ID"
  type        = string
  default     = "raw_github_events"
}

variable "raw_table_ttl_days" {
  description = "Retention period for raw tables (days)"
  type        = number
  default     = 30
}

variable "bucket_force_destroy" {
  description = "Allow deleting non-empty bucket"
  type        = bool
  default     = false
}
