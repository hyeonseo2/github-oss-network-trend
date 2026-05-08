# Operations Runbook

## 1. Normal daily operation

Workflow: `.github/workflows/pages.yml`

Expected behavior:

1. Scheduled run executes once per day (UTC).
2. `docs/data/*.json` is refreshed.
3. Pages deployment succeeds.

## 2. Manual refresh

1. Open `Actions`.
2. Select `Build and Deploy GitHub Pages`.
3. Click `Run workflow`.

Use this when:

- UI changed and needs immediate publish
- data refresh is needed before schedule

## 3. Fast checks

Check these files in the deployed branch:

- `docs/data/meta.json`
- `docs/data/trend_30d.json`
- `docs/data/network_30d.json`

Check these fields:

- `generated_at`
- `analysis_end_date`
- `rows`/`edges` length

## 4. Troubleshooting

### Case A: No data or very small data

Possible reasons:

- GitHub API rate limit
- low activity in selected repo set
- strict filter parameters

Actions:

1. Lower `MAX_REPOS` and rerun.
2. Lower `MIN_SHARED_COUNT` and rerun.
3. Increase `EVENT_MAX_PAGES` if network is too sparse.

### Case B: Network looks empty

Possible reasons:

- selected window has weak overlap
- edge strength slider too high
- search keyword narrows nodes too much

Actions:

1. Set edge strength to `1`.
2. Clear search filter.
3. Compare 7D, 14D, 30D windows.

### Case C: Workflow fails with API 403

Actions:

1. Ensure workflow uses `GITHUB_TOKEN`.
2. Lower `MAX_REPOS`.
3. Lower `EVENT_MAX_PAGES`.

## 5. Parameter tuning guide

- Faster run:
  - reduce `MAX_REPOS`
  - reduce `EVENT_MAX_PAGES`
- Denser network:
  - increase `MAX_REPOS`
  - increase `EVENT_MAX_PAGES`
  - decrease `MIN_SHARED_COUNT`
- Smaller payload:
  - reduce `TREND_TOP_N`
  - reduce `NETWORK_MAX_EDGES`
