# Cloud Run Dashboard Deploy

## 1) Required environment variables
- `GCP_PROJECT_ID` (recommended) or `PROJECT_ID`
  - Dashboard query target:
    - `<PROJECT>.oss_analytics_mart.mart_repo_trend`
    - `<PROJECT>.oss_analytics_mart.mart_contributor_edges`
- `BQ_LOCATION` must be the same as dataset location. This project default is `US`.

## 2) Deploy command (exact)
Run from repository root:

```bash
export GCP_PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
export BQ_LOCATION="US"
export REGION="us-central1"
export SERVICE_NAME="oss-analytics-dashboard"

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars "GCP_PROJECT_ID=${GCP_PROJECT_ID},PROJECT_ID=${GCP_PROJECT_ID},BQ_LOCATION=${BQ_LOCATION}"
```

## 3) Required IAM (Cloud Run runtime service account)
- BigQuery `roles/bigquery.jobUser`
- BigQuery dataset read access (`roles/bigquery.dataViewer`) on `oss_analytics_mart`
