{% test null_rate_below(model, column_name, max_null_rate) %}
WITH stats AS (
  SELECT
    COUNT(*) AS total_rows,
    COUNTIF({{ column_name }} IS NULL) AS null_rows
  FROM {{ model }}
)
SELECT
  *
FROM stats
WHERE SAFE_DIVIDE(null_rows, NULLIF(total_rows, 0)) > {{ max_null_rate }}
{% endtest %}

{% test row_count_drop_below(model, date_column, max_drop_ratio, value_column=None) %}
WITH daily_counts AS (
  SELECT
    {{ date_column }} AS dt,
    {% if value_column is not none %}
    SUM({{ value_column }}) AS row_count
    {% else %}
    COUNT(*) AS row_count
    {% endif %}
  FROM {{ model }}
  GROUP BY 1
),
ordered AS (
  SELECT
    dt,
    row_count,
    LAG(row_count) OVER (ORDER BY dt) AS prev_row_count
  FROM daily_counts
)
SELECT
  *
FROM ordered
WHERE prev_row_count IS NOT NULL
  AND prev_row_count > 0
  AND SAFE_DIVIDE(prev_row_count - row_count, prev_row_count) > {{ max_drop_ratio }}
{% endtest %}
