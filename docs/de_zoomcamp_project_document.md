# Data Engineering Zoomcamp Capstone Project Documentation

## Project name
**GitHub OSS Network Trend**

## 1) Project objective
Build an end-to-end data pipeline that detects how open-source repositories evolve over time and how developer communities connect repositories through shared contributors.

The project is implemented as a **batch pipeline on Google Cloud + GitHub Actions**, and delivers insights through a **Cloud Run dashboard**.

## 2) Problem statement
When many repositories are active on GitHub, identifying:

1. Which repositories are growing in activity,
2. How repository communities are connected through contributor overlap,

is difficult with only raw event streams.

This project solves that with two analytical views:

- **Trend view**: event activity + contributor change over time
- **Network view**: shared contributor edges between repositories

## 3) Data and architecture

### Data source
- **Public GitHub Events** from `githubarchive.day.YYYYMMDD`
- Event types used: `PushEvent`, `PullRequestEvent`, `IssuesEvent`
- Repository metadata is also requested from GitHub Search API for candidate selection.

### Architecture

```text
GitHub Archive -> GCS -> BigQuery Raw
    -> dbt Staging -> Intermediate -> Marts -> Cloud Run Dashboard
```

### Core tables/models

- `stg_github_events` (staging)
- `int_repo_daily_activity` (intermediate)
- `mart_repo_trend`
- `mart_contributor_edges`
- `mart_repo_popularity_snapshots`
- `pipeline_runs`

## 4) Data pipeline details

### Orchestration
- Workflow: `.github/workflows/oss-batch-pipeline.yml`
- Trigger: scheduled daily + manual dispatch
- Steps:
  1. resolve date/backfill window
  2. authenticate GCP
  3. ensure raw table schema
  4. export GitHub archive to GCS and load to BigQuery
  5. run `dbt run`
  6. run `dbt test`
  7. run quality SQL checks
  8. persist latest run metadata

### Transform layer
- `staging`: normalize event source to common schema
- `intermediate`: aggregate daily event/ contributor behavior by repo
- `marts`: business metrics for trend and contributor network

### Quality controls
- dbt tests are run each build
- additional SQL checks for:
  - row-null ratio gates
  - row-drop comparison gate vs previous day

## 5) Technologies

- **Cloud**: Google Cloud Platform (BigQuery, Cloud Run, GCS)
- **IaC**: Terraform
- **Orchestrator**: GitHub Actions
- **Transformation**: dbt + BigQuery SQL
- **Analytics App**: Flask + Jinja2 + Chart.js + vis-network
- **Language/runtime**: Python 3
- **Version control**: GitHub

## 6) Dashboard and user story

### Dashboard URL
- https://oss-analytics-dashboard-415500942280.us-central1.run.app/

### Required two tiles

- **Trend tile**
  - repository ranking and change bars
  - uses 7 / 14 / 30 day windows
  - default: **30 days**
- **Network tile**
  - shared-contributor network graph
  - filter by minimum shared contributor count and search
  - default: network shown

### Interpretable metric definition (event-based)
- `Activity Δ`: current window events - previous window events
- `Contributor Δ`: current window unique contributors - previous window unique contributors
- `Event Stars (window)`: window-level event volume (label only)
- `Active Contributors (window)`: window-level unique contributors (label only)

## 7) Reproducibility

- `make` targets and runbook are available in repository docs
- End-to-end reproducibility is based on:
  - `.env` configuration
  - Terraform deployment
  - GitHub Actions trigger
  - dbt run / dbt test
  - dashboard run/deploy


---

*This document was prepared as the dedicated project report for [Data Engineering Zoomcamp](https://datatalks.club/blog/data-engineering-zoomcamp.html) submission.*
