from __future__ import annotations

"""Flask dashboard service for OSS trend + contributor network metrics.

This app is a presentation layer; ingestion/transforms are handled via GitHub Actions + dbt.
"""

import os
import re
import threading
from datetime import datetime, timedelta
from typing import Any

import requests
from flask import Flask, render_template, request, redirect, url_for
from google.cloud import bigquery

app = Flask(__name__)

BLACKLIST_PATTERN = re.compile(r"(copilot|claude|codex)", re.IGNORECASE)
BLACKLIST_REGEX = BLACKLIST_PATTERN.pattern
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

GCP_PROJECT = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
BQ_LOCATION = os.getenv("BQ_LOCATION", "US")
MART_DATASET = os.getenv("MART_DATASET", "oss_analytics_mart")
MART_REPO_TREND_TABLE = "mart_repo_trend"
MART_CONTRIB_EDGES_TABLE = "mart_contributor_edges"
INT_REPO_DAILY_ACTIVITY_TABLE = "int_repo_daily_activity"
STG_GITHUB_EVENTS_TABLE = "stg_github_events"
PIPELINE_RUNS_TABLE = "pipeline_runs"
TREND_LIMIT = int(os.getenv("TREND_LIMIT", "120"))
TOP_TREND = int(os.getenv("TOP_TREND", "40"))
TREND_WINDOW_DAYS = int(os.getenv("TREND_WINDOW_DAYS", "30"))
DEFAULT_WINDOW_DAYS = TREND_WINDOW_DAYS
CACHE_TTL_SECONDS = int(os.getenv("DASHBOARD_CACHE_TTL_SECONDS", "43200"))
_QUERY_CACHE_TTL_SECONDS = int(os.getenv("QUERY_CACHE_TTL_SECONDS", "300"))
_DASHBOARD_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
_QUERY_CACHE: dict[str, tuple[datetime, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: str) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        entry = _DASHBOARD_CACHE.get(key)
        if not entry:
            return None
        exp, value = entry
        if (datetime.utcnow() - exp).total_seconds() > CACHE_TTL_SECONDS:
            _DASHBOARD_CACHE.pop(key, None)
            return None
        return value


def _cache_set(key: str, value: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _DASHBOARD_CACHE[key] = (datetime.utcnow(), value)


def _query_cache_get(key: str) -> Any | None:
    with _CACHE_LOCK:
        entry = _QUERY_CACHE.get(key)
        if not entry:
            return None
        exp, value = entry
        if (datetime.utcnow() - exp).total_seconds() > _QUERY_CACHE_TTL_SECONDS:
            _QUERY_CACHE.pop(key, None)
            return None
        return value


def _query_cache_set(key: str, value: Any) -> None:
    with _CACHE_LOCK:
        _QUERY_CACHE[key] = (datetime.utcnow(), value)


def _dashboard_cache_key(window_days: int, trend_mode: str, include_network: bool, project_id: str) -> str:
    return f"{project_id}:{trend_mode}:{window_days}:{1 if include_network else 0}"


def run_query(client: bigquery.Client, query: str, location: str | None = None) -> list[dict[str, Any]]:
    q = client.query(query, location=location)
    return [{k: row[k] for k in row.keys()} for row in q.result()]


def _sql_quote_identifier(value: str) -> str:
    return value.replace("'", "''")


def _safe_int(raw: str | None, default: int, min_v: int | None = None, max_v: int | None = None) -> int:
    try:
        v = int(raw or "")
    except Exception:
        return default
    if min_v is not None and v < min_v:
        v = min_v
    if max_v is not None and v > max_v:
        v = max_v
    return v


def _active_project() -> str:
    project = GCP_PROJECT or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError("GCP project id is not configured. Set GCP_PROJECT_ID/PROJECT_ID/GOOGLE_CLOUD_PROJECT.")
    return project


def _repo_in_clause(repo_names: list[str]) -> str:
    return _bq_string_array(repo_names)


def _repo_filter_expr(repo_names: list[str]) -> str:
    if not repo_names:
        return "FALSE"
    repo_list = _repo_in_clause(repo_names)
    if repo_list == "CAST([] AS ARRAY<STRING>)":
        return "FALSE"
    return f"repo_name IN UNNEST({repo_list})"


def _mart_repo_trend_table() -> str:
    return f"`{_active_project()}.{MART_DATASET}.{MART_REPO_TREND_TABLE}`"


def _mart_contributor_edges_table() -> str:
    return f"`{_active_project()}.{MART_DATASET}.{MART_CONTRIB_EDGES_TABLE}`"


def _int_repo_daily_activity_table() -> str:
    return f"`{_active_project()}.{MART_DATASET}.{INT_REPO_DAILY_ACTIVITY_TABLE}`"


def _stg_github_events_table() -> str:
    return f"`{_active_project()}.{MART_DATASET}.{STG_GITHUB_EVENTS_TABLE}`"


def _mart_repo_popularity_table() -> str:
    return f"`{_active_project()}.{MART_DATASET}.repo_popularity_snapshots`"


def _pipeline_runs_table() -> str:
    return f"`{_active_project()}.{MART_DATASET}.{PIPELINE_RUNS_TABLE}`"


def github_request_json(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oss-analytics-dashboard",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=12)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def search_popular_repos(window_days: int, mode: str = "trending") -> list[dict[str, Any]]:
    """Load candidate repos via GitHub Search API with short-lived cache.

    This keeps the UI-visible candidate set identical while avoiding repeated
    network calls for the same window/mode.
    """
    cache_key = f"search_popular_repos:{mode}:{window_days}"
    cached = _query_cache_get(cache_key)
    if cached is not None:
        return cached

    now = datetime.utcnow().date()
    since = (now - timedelta(days=window_days)).isoformat()

    # Primary query set by selected trend mode.
    queries = [
        f"pushed:>={since} stars:>=20 -is:archived",
        f"pushed:>={since} forks:>=10 -is:archived",
    ]
    if mode == "trending":
        queries = [
            f"pushed:>={since} stars:>=100 -is:archived",
            f"pushed:>={since} stars:>=40 forks:>=20 -is:archived",
            f"pushed:>={since} forks:>=50 -is:archived",
        ]
    elif mode == "balanced":
        queries = [
            f"pushed:>={since} stars:>=40 -is:archived",
            f"pushed:>={since} forks:>=10 -is:archived",
        ]
    else:
        queries = [
            f"pushed:>={since} stars:>=10 -is:archived",
            f"pushed:>={since} forks:>=2 -is:archived",
        ]

    def fetch(query_list: list[str]) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for q in query_list:
            payload = github_request_json(
                "https://api.github.com/search/repositories",
                {"q": q, "sort": "stars", "order": "desc", "per_page": 30},
            )
            if not payload:
                continue
            for it in payload.get("items", []) or []:
                name = str(it.get("full_name") or "")
                if not name or not REPO_NAME.match(name):
                    continue
                if BLACKLIST_PATTERN.search(name):
                    continue
                if name not in rows:
                    rows[name] = {
                        "repo_name": name,
                        # event-based baseline values are filled after BigQuery enrichment
                        "stars_total": 0,
                        "forks_total": 0,
                        "last_activity_date": str((it.get("pushed_at") or "")[:10]),
                    }
        return list(rows.values())

    results = fetch(queries)

    # Fallback: when window/mode is too strict, progressively relax constraints.
    if not results:
        fallback_queries = [
            f"pushed:>={since} stars:>=5 -is:archived",
            f"pushed:>={since} forks:>=1 -is:archived",
            f"pushed:>={since} -is:archived",
        ]
        results = fetch(fallback_queries)

    results = results[:TREND_LIMIT]
    _query_cache_set(cache_key, results)
    return results



def fetch_repo_trend_metrics(client: bigquery.Client, repos: list[dict[str, Any]], window_days: int) -> list[dict[str, Any]]:
    """Attach all trend/event/co-contributor metrics in one BigQuery pass.

    This preserves existing dashboard fields while reducing query round-trips.
    """
    if not repos:
        return []

    names = [str(r["repo_name"]) for r in repos if REPO_NAME.match(str(r.get("repo_name", "")))]
    if not names:
        return []

    repo_list = _repo_in_clause(names)
    if repo_list == "CAST([] AS ARRAY<STRING>)":
        return []

    analysis_end = "DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"
    curr_start = f"DATE_SUB({analysis_end}, INTERVAL {window_days} DAY)"
    prev_start = f"DATE_SUB({analysis_end}, INTERVAL {window_days * 2} DAY)"
    prev_end = f"DATE_SUB({analysis_end}, INTERVAL {window_days} DAY)"

    query = f"""
    WITH target_repos AS (
      SELECT repo_name FROM UNNEST({repo_list}) AS repo_name
    ),
    trend_daily AS (
      SELECT
        a.repo_name,
        a.activity_date,
        a.total_events
      FROM {_int_repo_daily_activity_table()} a
      JOIN target_repos t ON t.repo_name = a.repo_name
      WHERE a.activity_date BETWEEN {prev_start} AND {analysis_end}
    ),
    trend_contrib AS (
      SELECT
        s.repo_name,
        s.activity_date,
        s.contributor
      FROM {_stg_github_events_table()} s
      JOIN target_repos t ON t.repo_name = s.repo_name
      WHERE s.activity_date BETWEEN {prev_start} AND {analysis_end}
        AND s.contributor IS NOT NULL
    ),
    trend_agg AS (
      SELECT
        repo_name,
        SUM(IF(activity_date BETWEEN {curr_start} AND {analysis_end}, total_events, 0)) AS curr_events,
        SUM(IF(activity_date BETWEEN {prev_start} AND {prev_end}, total_events, 0)) AS prev_events
      FROM trend_daily
      GROUP BY repo_name
    ),
    contrib_agg AS (
      SELECT
        repo_name,
        COUNT(DISTINCT IF(activity_date BETWEEN {curr_start} AND {analysis_end}, contributor, NULL)) AS curr_contributors,
        COUNT(DISTINCT IF(activity_date BETWEEN {prev_start} AND {prev_end}, contributor, NULL)) AS prev_contributors,
        COUNT(DISTINCT IF(activity_date BETWEEN {curr_start} AND {analysis_end} AND NOT REGEXP_CONTAINS(LOWER(contributor), r'{BLACKLIST_REGEX}'), contributor, NULL)) AS curr_user_contributors,
        COUNT(DISTINCT IF(activity_date BETWEEN {prev_start} AND {prev_end} AND NOT REGEXP_CONTAINS(LOWER(contributor), r'{BLACKLIST_REGEX}'), contributor, NULL)) AS prev_user_contributors
      FROM trend_contrib
      GROUP BY repo_name
    )
    SELECT
      t.repo_name,
      CAST(IFNULL(a.curr_events, 0) AS INT64) AS curr_events,
      CAST(IFNULL(a.prev_events, 0) AS INT64) AS prev_events,
      CAST(IFNULL(c.curr_contributors, 0) AS INT64) AS curr_contributors,
      CAST(IFNULL(c.prev_contributors, 0) AS INT64) AS prev_contributors,
      CAST(IFNULL(c.curr_user_contributors, 0) AS INT64) AS curr_user_contributors,
      CAST(IFNULL(c.prev_user_contributors, 0) AS INT64) AS prev_user_contributors,
      CAST(IFNULL(a.curr_events, 0) - IFNULL(a.prev_events, 0) AS INT64) AS activity_delta_window,
      CAST(IFNULL(c.curr_contributors, 0) - IFNULL(c.prev_contributors, 0) AS INT64) AS contributors_delta_window
    FROM target_repos t
    LEFT JOIN trend_agg a USING (repo_name)
    LEFT JOIN contrib_agg c USING (repo_name)
    """

    rows = run_query(client, query, location=BQ_LOCATION)
    by_repo = {str(r["repo_name"]): r for r in rows}

    out: list[dict[str, Any]] = []
    for r in repos:
        repo_name = str(r.get("repo_name", ""))
        base = {
            "repo_name": repo_name,
            "stars_total": 0,
            "forks_total": 0,
            "activity_delta_window": 0,
            "contributors_delta_window": 0,
            "stars_delta_window": 0,
            "forks_delta_window": 0,
            "event_delta": 0,
            "contributor_delta": 0,
            "curr_event_count": 0,
            "prev_event_count": 0,
            "curr_contributor_count": 0,
            "prev_contributor_count": 0,
            "last_activity_date": str(r.get("last_activity_date", "")),
            "has_baseline": False,
            "has_exact_baseline": False,
        }
        row = by_repo.get(repo_name)
        if row:
            curr_events = int(row.get("curr_events", 0) or 0)
            prev_events = int(row.get("prev_events", 0) or 0)
            curr_contributors = int(row.get("curr_contributors", 0) or 0)
            prev_contributors = int(row.get("prev_contributors", 0) or 0)
            curr_user_contributors = int(row.get("curr_user_contributors", 0) or 0)
            prev_user_contributors = int(row.get("prev_user_contributors", 0) or 0)
            activity_delta = int(row.get("activity_delta_window", 0) or 0)
            contributors_delta = int(row.get("contributors_delta_window", 0) or 0)

            base.update(
                {
                    "stars_total": curr_events,
                    "forks_total": curr_contributors,
                    "activity_delta_window": activity_delta,
                    "contributors_delta_window": contributors_delta,
                    "stars_delta_window": activity_delta,
                    "forks_delta_window": contributors_delta,
                    "event_delta": activity_delta,
                    "contributor_delta": contributors_delta,
                    "curr_event_count": curr_events,
                    "prev_event_count": prev_events,
                    "curr_contributor_count": curr_user_contributors,
                    "prev_contributor_count": prev_user_contributors,
                    "has_baseline": (curr_events + curr_contributors > 0) or (prev_events + prev_contributors > 0),
                    "has_exact_baseline": (curr_events + curr_contributors > 0) and (prev_events + prev_contributors > 0),
                }
            )
        out.append(base)
    return out



def build_edge_chart_rows(edge_rows: list[dict[str, Any]], top_n: int = 15) -> list[dict[str, Any]]:
    if not edge_rows:
        return []

    degree: dict[str, int] = {}
    for r in edge_rows:
        source = str(r.get("source_repo", "")).strip()
        target = str(r.get("target_repo", "")).strip()
        shared = int(r.get("shared_contributor_count") or 0)
        if source:
            degree[source] = degree.get(source, 0) + shared
        if target:
            degree[target] = degree.get(target, 0) + shared

    return [
        {"repo_name": k, "degree": v}
        for k, v in sorted(degree.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[:top_n]
    ]




def fetch_pipeline_status(client: bigquery.Client) -> dict[str, Any] | None:
    query = f"""
    SELECT
      run_id,
      dag_id,
      run_started_at,
      executed_for_date,
      status,
      raw_events_rows
    FROM {_pipeline_runs_table()}
    ORDER BY run_started_at DESC
    LIMIT 1
    """
    try:
        rows = run_query(client, query, location=BQ_LOCATION)
        if not rows:
            return None
        r = rows[0]
        return {
            "run_id": str(r.get("run_id", "")),
            "dag_id": str(r.get("dag_id", "")),
            "status": str(r.get("status", "unknown")),
            "executed_for_date": str(r.get("executed_for_date", "")),
            "run_started_at": str(r.get("run_started_at", "")),
            "raw_events_rows": int(r.get("raw_events_rows", 0) or 0),
        }
    except Exception:
        return None

def fetch_repo_relation_edges(client: bigquery.Client, repo_names: list[str], window_days: int, min_shared_repo_count: int = 1) -> list[dict[str, Any]]:
    if not repo_names:
        return []
    repo_list = _repo_in_clause(repo_names)
    if repo_list == "CAST([] AS ARRAY<STRING>)":
        return []

    # Build repo-to-repo edges from staged events for selected repos (window-aware).
    stg_sql = f"""
    WITH target_repos AS (
      SELECT repo_name
      FROM UNNEST({repo_list}) AS repo_name
    ),
    repo_contributors AS (
      SELECT DISTINCT
        s.repo_name,
        s.contributor
      FROM {_stg_github_events_table()} s
      JOIN target_repos tr ON s.repo_name = tr.repo_name
      WHERE s.contributor IS NOT NULL
        AND s.activity_date BETWEEN DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY), INTERVAL {window_days} DAY) AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        AND NOT REGEXP_CONTAINS(LOWER(s.contributor), r'{BLACKLIST_REGEX}')
    ),
    paired AS (
      SELECT
        a.repo_name AS source_repo,
        b.repo_name AS target_repo,
        COUNT(DISTINCT a.contributor) AS shared_contributor_count
      FROM repo_contributors a
      JOIN repo_contributors b
        ON a.contributor = b.contributor
       AND a.repo_name < b.repo_name
      GROUP BY 1, 2
    )
    SELECT
      source_repo,
      target_repo,
      shared_contributor_count
    FROM paired
    WHERE shared_contributor_count >= {min_shared_repo_count}
    ORDER BY shared_contributor_count DESC
    LIMIT 400
    """
    return run_query(client, stg_sql, location=BQ_LOCATION)

def build_trend_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned: list[dict[str, Any]] = []
    for r in rows:
        activity_delta = int(r.get("activity_delta_window", r.get("stars_delta_window", 0)) or 0)
        contributors_delta = int(r.get("contributors_delta_window", r.get("forks_delta_window", 0)) or 0)
        row = dict(r)
        row["activity_delta_window"] = activity_delta
        row["contributors_delta_window"] = contributors_delta
        # keep legacy keys for template/JS compatibility
        row["stars_delta_window"] = activity_delta
        row["forks_delta_window"] = contributors_delta
        row["delta_score"] = activity_delta + contributors_delta
        cleaned.append(row)

    sorted_rows = sorted(
        cleaned,
        key=lambda x: (x["delta_score"], x.get("stars_total", 0), x.get("forks_total", 0)),
        reverse=True,
    )
    return sorted_rows[:TOP_TREND], sorted_rows[:TOP_TREND]




def _bq_string_array(values: list[str]) -> str:
    """Return a valid BigQuery array literal from a list of strings."""
    if not values:
        return 'CAST([] AS ARRAY<STRING>)'
    quoted = ', '.join(f"'{_sql_quote_identifier(str(v))}'" for v in values)
    return f"[{quoted}]"



@app.route("/")
def index():
    # For first-load consistency, keep default window on 30D
    if request.args.get("window") is None:
        return redirect(url_for("index", window=30, trend_mode="trending", network=request.args.get("network", "1")))

    allowed_window_days = {7, 14, 30}
    requested_window_days = _safe_int(request.args.get("window"), DEFAULT_WINDOW_DAYS, 1, 365)
    window_days = requested_window_days if requested_window_days in allowed_window_days else DEFAULT_WINDOW_DAYS
    # This UI keeps trend mode fixed to Trending only.
    trend_mode = "trending"

    include_network = request.args.get("network", "1") not in {"0", "false", "False", "off", "no", "0"}

    trend_rows: list[dict[str, Any]] = []
    trend_chart_rows: list[dict[str, Any]] = []
    user_event_rows: list[dict[str, Any]] = []
    user_event_chart_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    edge_chart_rows: list[dict[str, Any]] = []
    edge_graph_rows: list[dict[str, Any]] = []

    trend_error = None
    trend_warning = None
    edge_error = None
    pipeline_status = None
    trend_columns = ["repo_name", "activity_delta_window", "contributors_delta_window", "stars_total", "forks_total", "delta_score", "last_activity_date"]
    edge_columns = ["source_repo", "target_repo", "shared_contributor_count"]

    project_for_view = GCP_PROJECT or "(Not set)"
    try:
        project_for_view = _active_project()
    except Exception as e:
        trend_error = f"BigQuery client init failed: {e}"
        project_for_view = GCP_PROJECT or "(Not set)"

    cache_key = _dashboard_cache_key(window_days, trend_mode, include_network, project_for_view)
    cached = _cache_get(cache_key)
    if cached is not None:
        cached_values = cached
        trend_rows = cached_values.get("trend_rows", trend_rows)
        trend_chart_rows = cached_values.get("trend_chart_rows", trend_chart_rows)
        user_event_rows = cached_values.get("user_event_rows", user_event_rows)
        user_event_chart_rows = cached_values.get("user_event_chart_rows", user_event_chart_rows)
        edge_rows = cached_values.get("edge_rows", edge_rows)
        edge_chart_rows = cached_values.get("edge_chart_rows", edge_chart_rows)
        edge_graph_rows = cached_values.get("edge_graph_rows", edge_graph_rows)
        trend_error = cached_values.get("trend_error", trend_error)
        trend_warning = cached_values.get("trend_warning", trend_warning)
        edge_error = cached_values.get("edge_error", edge_error)
        pipeline_status = cached_values.get("pipeline_status", pipeline_status)
    else:
        client = None
        try:
            client = bigquery.Client(project=project_for_view)
        except Exception as e:
            trend_error = f"BigQuery client init failed: {e}"

        if client is not None:
            try:
                pipeline_status = fetch_pipeline_status(client)
                repos = search_popular_repos(window_days, trend_mode)
                if not repos:
                    trend_error = "No popular repositories found for this window/mode."
                else:
                    trend_rows = fetch_repo_trend_metrics(client, repos, window_days)
                    exact_baseline_count = sum(1 for r in trend_rows if r.get("has_exact_baseline", False))
                    baseline_count = sum(1 for r in trend_rows if r.get("has_baseline", False))
                    trend_rows, trend_chart_rows = build_trend_rows(trend_rows)

                    user_event_rows = trend_rows
                    user_event_chart_rows = user_event_rows

                    if include_network:
                        repo_names = [r["repo_name"] for r in trend_rows if r.get("repo_name")]
                        try:
                            edge_rows = fetch_repo_relation_edges(client, repo_names, window_days, 1)
                            edge_chart_rows = build_edge_chart_rows(edge_rows)
                            edge_graph_rows = edge_rows
                        except Exception as e:
                            edge_error = f"edge query failed: {e}"
                    else:
                        pass
                    _cache_set(
                        cache_key,
                        {
                            "trend_rows": trend_rows,
                            "trend_chart_rows": trend_chart_rows,
                            "user_event_rows": user_event_rows,
                            "user_event_chart_rows": user_event_chart_rows,
                            "edge_rows": edge_rows,
                            "edge_chart_rows": edge_chart_rows,
                            "edge_graph_rows": edge_graph_rows,
                            "trend_error": trend_error,
                            "trend_warning": trend_warning,
                            "edge_error": edge_error,
                            "pipeline_status": pipeline_status,
                        },
                    )
            except Exception as e:
                trend_error = f"Trend query failed: {e}"

    return render_template(
        "index.html",
        project_id=project_for_view,
        window_days=window_days,
        trend_mode=trend_mode,
        include_network=include_network,
        trend_columns=trend_columns,
        edge_columns=edge_columns,
        pipeline_status=pipeline_status,
        trend_rows=trend_rows,
        trend_chart_rows=trend_chart_rows,
        user_event_rows=user_event_rows,
        user_event_chart_rows=user_event_chart_rows,
        edge_rows=edge_rows,
        edge_chart_rows=edge_chart_rows,
        edge_graph_rows=edge_graph_rows,
        trend_error=trend_error,
        trend_warning=trend_warning,
        edge_error=edge_error,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
