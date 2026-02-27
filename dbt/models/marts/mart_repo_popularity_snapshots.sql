{{
  config(
    materialized='table'
  )
}}

{% set snapshot_window_days = var('analysis_window_days', 30) | int %}

WITH latest_window AS (
  SELECT
    MAX(activity_date) AS latest_activity_date
  FROM {{ ref('mart_repo_trend') }}
),
window_bounds AS (
  SELECT
    latest_activity_date,
    DATE_SUB(latest_activity_date, INTERVAL {{ snapshot_window_days }} DAY) AS window_start_date
  FROM latest_window
),
latest_repos AS (
  SELECT DISTINCT repo_name
  FROM {{ ref('mart_repo_trend') }}
  WHERE activity_date = (SELECT latest_activity_date FROM latest_window)
),
latest_events AS (
  SELECT
    repo_name,
    SUM(total_events) AS total_events_30d
  FROM {{ ref('int_repo_daily_activity') }}
  CROSS JOIN window_bounds b
  WHERE activity_date BETWEEN b.window_start_date AND b.latest_activity_date
  GROUP BY repo_name
),
latest_contributors AS (
  SELECT
    repo_name,
    COUNT(DISTINCT contributor) AS contributor_count
  FROM {{ ref('stg_github_events') }}
  CROSS JOIN window_bounds b
  WHERE activity_date BETWEEN b.window_start_date AND b.latest_activity_date
    AND contributor IS NOT NULL
  GROUP BY repo_name
)
SELECT
  CURRENT_DATE() AS snapshot_date,
  r.repo_name,
  CAST(IFNULL(e.total_events_30d, 0) AS INT64) AS event_total_30d,
  CAST(IFNULL(c.contributor_count, 0) AS INT64) AS active_contributor_count
FROM latest_repos r
LEFT JOIN latest_events e USING (repo_name)
LEFT JOIN latest_contributors c USING (repo_name)
WHERE r.repo_name IS NOT NULL
ORDER BY event_total_30d DESC, active_contributor_count DESC
