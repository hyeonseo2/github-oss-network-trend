# GitHub Pages Deployment Guide

This project deploys `docs/` to GitHub Pages using GitHub Actions.

## 1. Enable Pages from Actions

1. Open repository `Settings`.
2. Open `Pages`.
3. In `Build and deployment`, set `Source` to `GitHub Actions`.

## 2. Check workflow

Workflow file:

- `.github/workflows/pages.yml`

It runs on:

- Daily schedule (UTC)
- Manual run (`workflow_dispatch`)
- Push to `main` for docs/script/workflow changes

## 3. Trigger first build

1. Open `Actions` tab.
2. Select `Build and Deploy GitHub Pages`.
3. Click `Run workflow`.

After completion, the published URL appears in the deploy job output.

## 4. Optional tuning

Environment variables can be edited in workflow `Build static data snapshots` step:

- `MAX_REPOS`
- `TREND_TOP_N`
- `NETWORK_MAX_EDGES`
- `MIN_SHARED_COUNT`
- `REQUEST_SLEEP_MS`
- `HTTP_TIMEOUT_SECONDS`

Use lower values if you want faster runs and smaller JSON output.
