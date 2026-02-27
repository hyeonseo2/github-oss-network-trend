SELECT
  event_type,
  repo_name,
  contributor,
  created_at,
  DATE(created_at) AS activity_date
FROM `{{ var('gcp_project_id') }}.{{ var('raw_dataset') }}.{{ var('raw_table') }}`
WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {{ var('analysis_window_days', 30) }} DAY)
  AND event_type IN ('PushEvent', 'PullRequestEvent', 'IssuesEvent')
