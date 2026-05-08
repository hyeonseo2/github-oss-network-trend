# Data Engineering Zoomcamp Capstone Project Documentation

## Project name
**GitHub OSS Network Trend**

## 1) Project objective

Analyze open-source repository momentum and cross-repository contributor overlap.

Primary outputs:

- Trend view (activity/contributor deltas)
- Network view (shared-contributor edges)

## 2) Scope and evolution

This project originally started as a cloud pipeline (GCP + dbt + Cloud Run).
The current implementation was simplified to a GitHub-native pipeline for lower operational cost.

Current stack:

- GitHub Actions for scheduled batch generation
- GitHub REST API as data source
- GitHub Pages for dashboard hosting

## 3) Current architecture

```text
GitHub REST API
  -> GitHub Actions
  -> JSON snapshots in docs/data
  -> GitHub Pages dashboard
```

## 4) Data model

Generated files:

- `meta.json`
- `trend_7d.json`, `trend_14d.json`, `trend_30d.json`
- `network_7d.json`, `network_14d.json`, `network_30d.json`
- `top_repos.json`

Key fields:

- `activity_delta`
- `contributor_delta`
- `trend_score`
- `shared_contributor_count`

## 5) Pipeline behavior

Workflow: `.github/workflows/pages.yml`

Steps:

1. Select candidate repositories from GitHub Search API
2. Pull repository events and contributors
3. Build trend/network metrics for 7D/14D/30D windows
4. Publish `docs/` to GitHub Pages

## 6) UI behavior

- Window filters: 7D / 14D / 30D
- Search filter by repository name
- Network edge-strength slider (`min shared contributors`)
- Node click interaction:
  - connected nodes/edges are highlighted
  - non-connected elements are dimmed

## 7) Quality and limitations

- Data freshness depends on GitHub Actions schedule
- API rate limits can reduce repository coverage
- Results represent sampled repository activity, not full GitHub ground truth

## 8) Reproducibility

Local:

```bash
cp .env.example .env
source .env
make build-data
make run-site
```

Hosted:

- GitHub Actions + GitHub Pages from the repository main branch

---

Prepared for the [Data Engineering Zoomcamp](https://datatalks.club/blog/data-engineering-zoomcamp.html) capstone submission context, with architecture notes updated to reflect the current implementation.
