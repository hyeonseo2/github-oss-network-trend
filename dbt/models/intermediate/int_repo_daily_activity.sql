SELECT
  activity_date,
  repo_name,
  COUNT(*) AS total_events
FROM {{ ref('stg_github_events') }}
GROUP BY 1, 2
