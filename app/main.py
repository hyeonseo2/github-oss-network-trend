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
_DASHBOARD_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
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
                        # event-based baseline values are filled after BigQuery delta enrichment
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

    return results[:TREND_LIMIT]





def attach_star_fork_deltas(client: bigquery.Client, repos: list[dict[str, Any]], window_days: int) -> list[dict[str, Any]]:
    """Attach trend-style deltas for dashboard metrics.

    NOTE: These are activity-based metrics derived from events in the mart,
    not GitHub star/fork counts. The display labels are intentionally normalized
    in the caller/template to avoid metric confusion.
    """
    if not repos:
        return []

    names = [str(r["repo_name"]) for r in repos if REPO_NAME.match(str(r.get("repo_name", "")))]
    if not names:
        return repos

    repo_list = _repo_in_clause(names)
    analysis_end = "DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"
    curr_start = f"DATE_SUB({analysis_end}, INTERVAL {window_days} DAY)"
    prev_start = f"DATE_SUB({analysis_end}, INTERVAL {window_days * 2} DAY)"
    prev_end = f"DATE_SUB({analysis_end}, INTERVAL {window_days} DAY)"

    delta_sql = f"""
    WITH target AS (
      SELECT repo_name FROM UNNEST({repo_list}) AS repo_name
    ),
    curr_window AS (
      SELECT
        repo_name,
        SUM(COALESCE(total_events, 0)) AS curr_events
      FROM {_int_repo_daily_activity_table()}
      WHERE activity_date BETWEEN {curr_start} AND {analysis_end}
        AND repo_name IN (SELECT repo_name FROM target)
      GROUP BY repo_name
    ),
    prev_window AS (
      SELECT
        repo_name,
        SUM(COALESCE(total_events, 0)) AS prev_events
      FROM {_int_repo_daily_activity_table()}
      WHERE activity_date BETWEEN {prev_start} AND {prev_end}
        AND repo_name IN (SELECT repo_name FROM target)
      GROUP BY repo_name
    ),
    curr_contrib AS (
      SELECT
        repo_name,
        COUNT(DISTINCT contributor) AS curr_contributors
      FROM {_stg_github_events_table()}
      WHERE activity_date BETWEEN {curr_start} AND {analysis_end}
        AND repo_name IN (SELECT repo_name FROM target)
      GROUP BY repo_name
    ),
    prev_contrib AS (
      SELECT
        repo_name,
        COUNT(DISTINCT contributor) AS prev_contributors
      FROM {_stg_github_events_table()}
      WHERE activity_date BETWEEN {prev_start} AND {prev_end}
        AND repo_name IN (SELECT repo_name FROM target)
      GROUP BY repo_name
    )
    SELECT
      t.repo_name,
      IFNULL(cw.curr_events, 0) AS curr_events,
      IFNULL(pw.prev_events, 0) AS prev_events,
      IFNULL(cn.curr_contributors, 0) AS curr_contributors,
      IFNULL(pn.prev_contributors, 0) AS prev_contributors,
      IFNULL(cw.curr_events, 0) - IFNULL(pw.prev_events, 0) AS activity_delta_window,
      IFNULL(cn.curr_contributors, 0) - IFNULL(pn.prev_contributors, 0) AS contributors_delta_window
    FROM target t
    LEFT JOIN curr_window cw USING (repo_name)
    LEFT JOIN prev_window pw USING (repo_name)
    LEFT JOIN curr_contrib cn USING (repo_name)
    LEFT JOIN prev_contrib pn USING (repo_name)
    """

    try:
        rows = run_query(client, delta_sql, location=BQ_LOCATION)
        map_rows = {
            str(r["repo_name"]): {
                "stars_total": int(r.get("curr_events", 0) or 0),
                "forks_total": int(r.get("curr_contributors", 0) or 0),
                "activity_delta_window": int(r.get("activity_delta_window", 0) or 0),
                "contributors_delta_window": int(r.get("contributors_delta_window", 0) or 0),
                "stars_delta_window": int(r.get("activity_delta_window", 0) or 0),
                "forks_delta_window": int(r.get("contributors_delta_window", 0) or 0),
                "has_baseline": (int(r.get("curr_events", 0) or 0) + int(r.get("curr_contributors", 0) or 0) > 0)
                or (int(r.get("prev_events", 0) or 0) + int(r.get("prev_contributors", 0) or 0) > 0),
                "has_exact_baseline": (int(r.get("curr_events", 0) or 0) + int(r.get("curr_contributors", 0) or 0) > 0)
                and (int(r.get("prev_events", 0) or 0) + int(r.get("prev_contributors", 0) or 0) > 0),
            }
            for r in rows
        }
    except Exception:
        map_rows = {}

    out: list[dict[str, Any]] = []
    for r in repos:
        repo_name = str(r.get("repo_name", ""))
        base = {
            "repo_name": repo_name,
            "stars_total": int(r.get("stars_total", 0) or 0),
            "forks_total": int(r.get("forks_total", 0) or 0),
            "activity_delta_window": 0,
            "contributors_delta_window": 0,
            "stars_delta_window": 0,
            "forks_delta_window": 0,
            "last_activity_date": str(r.get("last_activity_date", "")),
            "has_baseline": False,
            "has_exact_baseline": False,
        }
        if repo_name in map_rows:
            base.update(map_rows[repo_name])
        out.append(base)
    return out


def attach_user_event_deltas(client: bigquery.Client, repos: list[dict[str, Any]], window_days: int) -> list[dict[str, Any]]:
    if not repos:
        return []

    names = [str(r["repo_name"]) for r in repos if REPO_NAME.match(str(r.get("repo_name", "")))]
    if not names:
        return []

    repo_list = _repo_in_clause(names)
    if repo_list == "[]":
        return []

    analysis_end = "DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"
    curr_start = f"DATE_SUB({analysis_end}, INTERVAL {window_days} DAY)"
    prev_start = f"DATE_SUB({analysis_end}, INTERVAL {window_days * 2} DAY)"
    prev_end = f"DATE_SUB({analysis_end}, INTERVAL {window_days} DAY)"

    event_sql = f"""
    WITH target_repos AS (
      SELECT repo_name FROM UNNEST({repo_list}) AS repo_name
    ),
    curr AS (
      SELECT
        repo_name,
        SUM(total_events) AS event_count
      FROM {_int_repo_daily_activity_table()}
      JOIN target_repos USING (repo_name)
      WHERE activity_date BETWEEN {curr_start}
        AND {analysis_end}
      GROUP BY repo_name
    ),
    prev AS (
      SELECT
        repo_name,
        SUM(total_events) AS event_count
      FROM {_int_repo_daily_activity_table()}
      JOIN target_repos USING (repo_name)
      WHERE activity_date BETWEEN {prev_start}
        AND {prev_end}
      GROUP BY repo_name
    ),
    curr_contrib AS (
      SELECT
        repo_name,
        COUNT(DISTINCT contributor) AS contributor_count
      FROM {_stg_github_events_table()}
      JOIN target_repos USING (repo_name)
      WHERE activity_date BETWEEN {curr_start}
        AND {analysis_end}
        AND contributor IS NOT NULL
        AND NOT REGEXP_CONTAINS(LOWER(contributor), r'{BLACKLIST_REGEX}')
      GROUP BY repo_name
    ),
    prev_contrib AS (
      SELECT
        repo_name,
        COUNT(DISTINCT contributor) AS contributor_count
      FROM {_stg_github_events_table()}
      JOIN target_repos USING (repo_name)
      WHERE activity_date BETWEEN {prev_start}
        AND {prev_end}
        AND contributor IS NOT NULL
        AND NOT REGEXP_CONTAINS(LOWER(contributor), r'{BLACKLIST_REGEX}')
      GROUP BY repo_name
    )
    SELECT
      tr.repo_name,
      IFNULL(c.event_count, 0) AS curr_event_count,
      IFNULL(p.event_count, 0) AS prev_event_count,
      IFNULL(cc.contributor_count, 0) AS curr_contributor_count,
      IFNULL(pc.contributor_count, 0) AS prev_contributor_count,
      IFNULL(c.event_count, 0) - IFNULL(p.event_count, 0) AS event_delta,
      IFNULL(cc.contributor_count, 0) - IFNULL(pc.contributor_count, 0) AS contributor_delta
    FROM target_repos tr
    LEFT JOIN curr c USING (repo_name)
    LEFT JOIN prev p USING (repo_name)
    LEFT JOIN curr_contrib cc USING (repo_name)
    LEFT JOIN prev_contrib pc USING (repo_name)
    """

    rows = run_query(client, event_sql, location=BQ_LOCATION)
    row_map = {
        str(r["repo_name"]): {
            "event_delta": int(r.get("event_delta", 0) or 0),
            "contributor_delta": int(r.get("contributor_delta", 0) or 0),
            "curr_event_count": int(r.get("curr_event_count", 0) or 0),
            "prev_event_count": int(r.get("prev_event_count", 0) or 0),
            "curr_contributor_count": int(r.get("curr_contributor_count", 0) or 0),
            "prev_contributor_count": int(r.get("prev_contributor_count", 0) or 0),
        }
        for r in rows
    }

    out: list[dict[str, Any]] = []
    for r in repos:
        repo_name = str(r.get("repo_name", ""))
        stats = row_map.get(
            repo_name,
            {
                "event_delta": 0,
                "contributor_delta": 0,
                "curr_event_count": 0,
                "prev_event_count": 0,
                "curr_contributor_count": 0,
                "prev_contributor_count": 0,
            },
        )
        out.append({"repo_name": repo_name, **stats})
    return out


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
    if repo_list == "[]":
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

def fetch_edge_chart_rows(client: bigquery.Client, repo_names: list[str], window_days: int, top_n: int = 15) -> list[dict[str, Any]]:
    if not repo_names:
        return []
    repo_list = _repo_in_clause(repo_names)
    if repo_list == "[]":
        return []

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
    ),
    exploded AS (
      SELECT source_repo AS repo_name, shared_contributor_count FROM paired
      UNION ALL
      SELECT target_repo AS repo_name, shared_contributor_count FROM paired
    )
    SELECT
      repo_name,
      SUM(shared_contributor_count) AS degree
    FROM exploded
    GROUP BY repo_name
    ORDER BY degree DESC
    LIMIT {top_n}
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
                    trend_with_delta = attach_star_fork_deltas(client, repos, window_days)
                    exact_baseline_count = sum(1 for r in trend_with_delta if r.get("has_exact_baseline", False))
                    baseline_count = sum(1 for r in trend_with_delta if r.get("has_baseline", False))
                    trend_rows, trend_chart_rows = build_trend_rows(trend_with_delta)

                    user_event_rows = attach_user_event_deltas(client, trend_rows, window_days)
                    user_event_chart_rows = user_event_rows

                    if include_network:
                        repo_names = [r["repo_name"] for r in trend_rows if r.get("repo_name")]
                        try:
                            edge_rows = fetch_repo_relation_edges(client, repo_names, window_days, 1)
                            edge_chart_rows = fetch_edge_chart_rows(client, repo_names, window_days, 15)
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
