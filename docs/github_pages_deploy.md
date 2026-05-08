# GitHub Pages Deployment Guide

This repository deploys `docs/` using GitHub Actions.

## 1. Enable Pages

1. Open repository `Settings`.
2. Open `Pages`.
3. Set `Source` to `GitHub Actions`.

## 2. Workflow

Workflow file: `.github/workflows/pages.yml`

Triggers:

- Daily schedule (UTC)
- Manual run (`workflow_dispatch`)
- Push to `main` for docs/script/workflow changes

## 3. What the workflow does

1. Builds data snapshots with `scripts/build_data.py`
2. Writes JSON files into `docs/data/`
3. Deploys the `docs/` directory to GitHub Pages

## 4. Runtime parameters

Configured in the workflow env block:

- `MAX_REPOS`
- `TREND_TOP_N`
- `NETWORK_MAX_EDGES`
- `MIN_SHARED_COUNT`
- `REQUEST_SLEEP_MS`
- `HTTP_TIMEOUT_SECONDS`
- `EVENT_MAX_PAGES`

## 5. First deployment

1. Go to `Actions`.
2. Select `Build and Deploy GitHub Pages`.
3. Click `Run workflow`.
4. After success, open the page URL shown in the deploy job output.

## 6. Common issues

- 403 rate limit from GitHub API:
  - Keep `GITHUB_TOKEN` enabled in workflow env
  - Reduce `MAX_REPOS` or `EVENT_MAX_PAGES`
- Network view has too few edges:
  - Decrease `MIN_SHARED_COUNT`
  - Increase `EVENT_MAX_PAGES`
