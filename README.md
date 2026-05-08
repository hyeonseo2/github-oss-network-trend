# GitHub OSS Network Trend (Static Edition)

[English](./README.md) | [한국어](./README.ko.md)

This project is now a static analytics dashboard hosted on GitHub Pages.
It no longer uses BigQuery, Cloud Run, dbt, or Terraform.

## Overview

- Data source: GitHub REST API
- Batch runner: GitHub Actions (daily)
- Output: `docs/data/*.json`
- Hosting: GitHub Pages

## Architecture

```text
GitHub API
   |
   v
GitHub Actions (scheduled)
   |
   v
scripts/build_static_data.py
   |
   v
docs/data/*.json
   |
   v
GitHub Pages (docs/)
```

## Quick start

1. Configure environment variables.
2. Generate static data.
3. Serve the static site locally.

```bash
cp .env.example .env
source .env

make build-data
make run-site
```

Open `http://127.0.0.1:8080`.

## GitHub Pages deployment

The repository includes a Pages workflow:

- [pages.yml](.github/workflows/pages.yml)

The workflow:

1. Runs daily (UTC) and on manual dispatch.
2. Generates fresh JSON snapshots into `docs/data`.
3. Deploys the `docs/` directory to GitHub Pages.

Setup guide:

- [GitHub Pages deployment guide](docs/github_pages_deploy.md)

## Output data files

- `docs/data/meta.json`
- `docs/data/trend_7d.json`
- `docs/data/trend_14d.json`
- `docs/data/trend_30d.json`
- `docs/data/network_30d.json`
- `docs/data/top_repos.json`

## Cost profile after migration

- BigQuery: removed
- Cloud Run: removed
- GCP infra: removed
- Ongoing cost driver: GitHub Actions usage and GitHub Pages traffic

For public repositories, standard GitHub-hosted runner usage is free under GitHub's policy.

