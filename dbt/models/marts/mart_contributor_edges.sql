{% set window_days = var('network_window_days', 30) %}
{% set default_min_shared = 1 if window_days | int <= 30 else 2 %}
{% set min_shared = var('min_shared_repo_count', default_min_shared) %}
{% set min_repo_events = var('min_daily_events_for_trend', 5) %}

WITH latest_snapshot AS (
  SELECT MAX(activity_date) AS latest_activity_date
  FROM {{ ref('mart_repo_trend') }}
),
candidate_repos AS (
  SELECT DISTINCT repo_name
  FROM {{ ref('mart_repo_trend') }}, latest_snapshot
  WHERE activity_date = latest_snapshot.latest_activity_date
    AND total_events >= {{ min_repo_events }}
),
repo_contributors AS (
  SELECT DISTINCT
    r.repo_name,
    r.contributor
  FROM {{ ref('stg_github_events') }} r
  JOIN candidate_repos c
    ON r.repo_name = c.repo_name
  WHERE r.contributor IS NOT NULL
    AND r.activity_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {{ window_days }} DAY)
    AND NOT REGEXP_CONTAINS(LOWER(r.contributor), r'(\[bot\]$|-bot$|^bot-)')
),
pair_sources AS (
  SELECT
    contributor,
    ARRAY_AGG(DISTINCT repo_name ORDER BY repo_name) AS repos
  FROM repo_contributors
  GROUP BY contributor
  HAVING ARRAY_LENGTH(ARRAY_AGG(DISTINCT repo_name)) >= 2
),
paired AS (
  SELECT
    repo_a AS source_repo,
    repo_b AS target_repo,
    COUNT(1) AS shared_contributor_count
  FROM pair_sources ps
  JOIN UNNEST(ps.repos) AS repo_a WITH OFFSET off_a
  JOIN UNNEST(ps.repos) AS repo_b WITH OFFSET off_b
    ON off_a < off_b
  GROUP BY 1, 2
)
SELECT
  source_repo,
  target_repo,
  shared_contributor_count,
  {{ window_days }} AS window_days,
  {{ min_shared }} AS min_shared_repo_threshold,
  CURRENT_DATE() AS snapshot_date
FROM paired
WHERE shared_contributor_count >= {{ min_shared }}
