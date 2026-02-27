SELECT
  repo_name,
  contributor,
  COUNT(*) AS contribution_events
FROM {{ ref('stg_github_events') }}
WHERE contributor IS NOT NULL
GROUP BY 1, 2
