WITH daily AS (
  SELECT
    activity_date,
    repo_name,
    total_events
  FROM {{ ref('int_repo_daily_activity') }}
),
windowed AS (
  SELECT
    activity_date,
    repo_name,
    total_events,
    AVG(total_events) OVER (
      PARTITION BY repo_name
      ORDER BY activity_date
      ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS rolling_7d_avg
  FROM daily
)
SELECT
  activity_date,
  repo_name,
  total_events,
  rolling_7d_avg,
  CASE
    WHEN total_events < {{ var('min_daily_events_for_trend', 5) }} THEN NULL
    ELSE SAFE_DIVIDE(total_events, NULLIF(rolling_7d_avg, 0))
  END AS trend_ratio,
  CASE
    WHEN total_events < {{ var('min_daily_events_for_trend', 5) }} THEN 'low_activity_excluded'
    WHEN SAFE_DIVIDE(total_events, NULLIF(rolling_7d_avg, 0)) >= 2 THEN 'accelerating'
    WHEN SAFE_DIVIDE(total_events, NULLIF(rolling_7d_avg, 0)) >= 1 THEN 'stable_growth'
    ELSE 'declining_or_flat'
  END AS trend_status,
  CURRENT_DATE() AS snapshot_date
FROM windowed
WHERE activity_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {{ var('trend_output_days', 30) }} DAY)
