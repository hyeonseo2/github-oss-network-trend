#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.github.com"
EVENT_TYPES = {"PushEvent", "PullRequestEvent", "IssuesEvent"}
WINDOWS = (7, 14, 30)
BOT_FRAGMENTS = ("[bot]", "-bot", "bot-")


def _env_int(name: str, default: int, min_v: int, max_v: int) -> int:
    raw = os.getenv(name, "")
    try:
        value = int(raw)
    except Exception:
        return default
    if value < min_v:
        return min_v
    if value > max_v:
        return max_v
    return value


def _iso_now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_bot(login: str) -> bool:
    low = login.lower()
    return any(fragment in low for fragment in BOT_FRAGMENTS)


@dataclass
class RepoSnapshot:
    repo_name: str
    repo_url: str
    stars_total: int
    forks_total: int
    description: str
    last_activity_date: str | None
    network_contributors: list[str]
    windows: dict[int, dict[str, Any]]


class GitHubClient:
    def __init__(self, token: str | None, timeout_seconds: int) -> None:
        self.token = token
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = urlencode(params or {}, doseq=True)
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{query}"

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "oss-network-static-builder",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None:
                    try:
                        if int(remaining) < 50:
                            print(f"[warn] low GitHub API rate limit remaining: {remaining}", file=sys.stderr)
                    except Exception:
                        pass
                return json.loads(body)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"GitHub API error {exc.code} for {url}: {detail[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc


def search_repositories(client: GitHubClient, max_repos: int, since_date: date) -> list[dict[str, Any]]:
    since = since_date.isoformat()
    queries = [
        f"pushed:>={since} stars:>=100 archived:false",
        f"pushed:>={since} stars:>=40 forks:>=20 archived:false",
        f"pushed:>={since} forks:>=40 archived:false",
    ]
    fallback_query = f"pushed:>={since} stars:>=10 archived:false"

    rows: dict[str, dict[str, Any]] = {}

    def add_items(items: list[dict[str, Any]]) -> None:
        for item in items:
            full_name = str(item.get("full_name") or "")
            if full_name.count("/") != 1:
                continue
            if full_name not in rows:
                rows[full_name] = {
                    "repo_name": full_name,
                    "repo_url": str(item.get("html_url") or f"https://github.com/{full_name}"),
                    "stars_total": int(item.get("stargazers_count") or 0),
                    "forks_total": int(item.get("forks_count") or 0),
                    "description": str(item.get("description") or ""),
                }

    def run_query(query: str) -> None:
        for page in (1, 2):
            payload = client.get_json(
                "/search/repositories",
                {
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": 50,
                    "page": page,
                },
            )
            items = payload.get("items", [])
            if not items:
                break
            add_items(items)
            if len(rows) >= max_repos:
                return

    for query in queries:
        run_query(query)
        if len(rows) >= max_repos:
            break

    if len(rows) < max_repos // 2:
        run_query(fallback_query)

    return list(rows.values())[:max_repos]


def fetch_repo_events(client: GitHubClient, repo_name: str) -> list[tuple[date, str]]:
    try:
        payload = client.get_json(f"/repos/{repo_name}/events", {"per_page": 100})
    except RuntimeError as exc:
        print(f"[warn] skip events for {repo_name}: {exc}", file=sys.stderr)
        return []

    rows: list[tuple[date, str]] = []
    for event in payload:
        event_type = str(event.get("type") or "")
        if event_type not in EVENT_TYPES:
            continue

        created_at = str(event.get("created_at") or "")
        try:
            event_date = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").date()
        except Exception:
            continue

        actor = str((event.get("actor") or {}).get("login") or "")
        rows.append((event_date, actor))

    return rows


def fetch_repo_contributors(client: GitHubClient, repo_name: str) -> list[str]:
    try:
        payload = client.get_json(
            f"/repos/{repo_name}/contributors",
            {"per_page": 100, "page": 1, "anon": "false"},
        )
    except RuntimeError as exc:
        print(f"[warn] skip contributors for {repo_name}: {exc}", file=sys.stderr)
        return []

    if not isinstance(payload, list):
        return []

    contributors: set[str] = set()
    for row in payload:
        login = str((row or {}).get("login") or "")
        if not login:
            continue
        if _is_bot(login):
            continue
        contributors.add(login)
    return sorted(contributors)


def build_windows(events: list[tuple[date, str]], analysis_end: date) -> tuple[dict[int, dict[str, Any]], str | None]:
    windows: dict[int, dict[str, Any]] = {}
    last_activity: date | None = None

    for event_date, _ in events:
        if event_date <= analysis_end and (last_activity is None or event_date > last_activity):
            last_activity = event_date

    for window_days in WINDOWS:
        current_start = analysis_end - timedelta(days=window_days - 1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=window_days - 1)

        activity_current = 0
        activity_previous = 0
        contributors_current: set[str] = set()
        contributors_previous: set[str] = set()

        for event_date, contributor in events:
            if current_start <= event_date <= analysis_end:
                activity_current += 1
                if contributor and not _is_bot(contributor):
                    contributors_current.add(contributor)
            elif previous_start <= event_date <= previous_end:
                activity_previous += 1
                if contributor and not _is_bot(contributor):
                    contributors_previous.add(contributor)

        contributor_current_count = len(contributors_current)
        contributor_previous_count = len(contributors_previous)

        windows[window_days] = {
            "activity_current": activity_current,
            "activity_previous": activity_previous,
            "activity_delta": activity_current - activity_previous,
            "contributors_current": contributor_current_count,
            "contributors_previous": contributor_previous_count,
            "contributor_delta": contributor_current_count - contributor_previous_count,
            "contributors_set": sorted(contributors_current),
        }

    return windows, (last_activity.isoformat() if last_activity else None)


def build_repo_snapshot(
    repo: dict[str, Any],
    events: list[tuple[date, str]],
    analysis_end: date,
    fallback_network_contributors: list[str],
) -> RepoSnapshot:
    windows, last_activity_date = build_windows(events, analysis_end)
    network_contributors: set[str] = set(fallback_network_contributors)
    network_contributors.update(windows[30]["contributors_set"])
    return RepoSnapshot(
        repo_name=repo["repo_name"],
        repo_url=repo["repo_url"],
        stars_total=int(repo["stars_total"]),
        forks_total=int(repo["forks_total"]),
        description=str(repo["description"]),
        last_activity_date=last_activity_date,
        network_contributors=sorted(network_contributors),
        windows=windows,
    )


def build_trend_rows(
    snapshots: list[RepoSnapshot],
    window_days: int,
    top_n: int,
    analysis_end: date,
    generated_at: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for snap in snapshots:
        metrics = snap.windows[window_days]
        if metrics["activity_current"] == 0 and metrics["contributors_current"] == 0:
            continue

        trend_score = float(metrics["activity_delta"]) + (2.0 * float(metrics["contributor_delta"]))
        row = {
            "repo_name": snap.repo_name,
            "repo_url": snap.repo_url,
            "activity_current": metrics["activity_current"],
            "activity_previous": metrics["activity_previous"],
            "activity_delta": metrics["activity_delta"],
            "contributors_current": metrics["contributors_current"],
            "contributors_previous": metrics["contributors_previous"],
            "contributor_delta": metrics["contributor_delta"],
            "event_stars_window": metrics["activity_current"],
            "active_contributors_window": metrics["contributors_current"],
            "stars_total": snap.stars_total,
            "forks_total": snap.forks_total,
            "last_activity_date": snap.last_activity_date,
            "trend_score": round(trend_score, 3),
            "description": snap.description,
        }
        rows.append(row)

    rows.sort(
        key=lambda row: (
            row["trend_score"],
            row["activity_current"],
            row["contributors_current"],
            row["stars_total"],
        ),
        reverse=True,
    )

    return {
        "window_days": window_days,
        "analysis_end_date": analysis_end.isoformat(),
        "generated_at": generated_at,
        "rows": rows[:top_n],
    }


def build_network(
    snapshots: list[RepoSnapshot],
    window_days: int,
    max_edges: int,
    min_shared_count: int,
    analysis_end: date,
    generated_at: str,
) -> dict[str, Any]:
    repo_lookup = {snap.repo_name: snap for snap in snapshots}
    contributor_to_repos: dict[str, set[str]] = defaultdict(set)

    for snap in snapshots:
        metrics = snap.windows[window_days]
        if metrics["activity_current"] <= 0:
            continue
        contributors = snap.network_contributors or metrics["contributors_set"]
        for contributor in contributors:
            if contributor:
                contributor_to_repos[contributor].add(snap.repo_name)

    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for repos in contributor_to_repos.values():
        if len(repos) < 2:
            continue
        for source_repo, target_repo in combinations(sorted(repos), 2):
            pair_counts[(source_repo, target_repo)] += 1

    edges: list[dict[str, Any]] = []
    for (source_repo, target_repo), count in pair_counts.items():
        if count < min_shared_count:
            continue
        edges.append(
            {
                "source_repo": source_repo,
                "target_repo": target_repo,
                "shared_contributor_count": count,
            }
        )

    edges.sort(
        key=lambda edge: (
            edge["shared_contributor_count"],
            edge["source_repo"],
            edge["target_repo"],
        ),
        reverse=True,
    )
    edges = edges[:max_edges]

    node_names: set[str] = set()
    for edge in edges:
        node_names.add(edge["source_repo"])
        node_names.add(edge["target_repo"])

    if not node_names:
        top_activity = sorted(
            snapshots,
            key=lambda snap: snap.windows[window_days]["activity_current"],
            reverse=True,
        )
        node_names = {snap.repo_name for snap in top_activity[:20]}

    nodes: list[dict[str, Any]] = []
    for repo_name in sorted(node_names):
        snap = repo_lookup.get(repo_name)
        if snap is None:
            continue
        metrics = snap.windows[window_days]
        nodes.append(
            {
                "id": repo_name,
                "label": repo_name,
                "repo_url": snap.repo_url,
                "events_window": metrics["activity_current"],
                "contributors_window": metrics["contributors_current"],
                "stars_total": snap.stars_total,
                "forks_total": snap.forks_total,
            }
        )

    return {
        "window_days": window_days,
        "analysis_end_date": analysis_end.isoformat(),
        "generated_at": generated_at,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "min_shared_count": min_shared_count,
        },
    }


def write_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(value, fp, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static JSON snapshots for GitHub Pages dashboard")
    parser.add_argument("--output", default="docs/data", help="Output directory for JSON files")
    parser.add_argument("--max-repos", type=int, default=_env_int("MAX_REPOS", 80, 10, 300))
    parser.add_argument("--trend-top-n", type=int, default=_env_int("TREND_TOP_N", 40, 10, 200))
    parser.add_argument("--network-max-edges", type=int, default=_env_int("NETWORK_MAX_EDGES", 240, 20, 1000))
    parser.add_argument("--min-shared-count", type=int, default=_env_int("MIN_SHARED_COUNT", 1, 1, 10))
    parser.add_argument("--sleep-ms", type=int, default=_env_int("REQUEST_SLEEP_MS", 80, 0, 3000))
    parser.add_argument("--http-timeout", type=int, default=_env_int("HTTP_TIMEOUT_SECONDS", 20, 5, 120))
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    client = GitHubClient(token=token, timeout_seconds=args.http_timeout)

    analysis_end = datetime.now(timezone.utc).date() - timedelta(days=1)
    since_date = analysis_end - timedelta(days=30)
    generated_at = _iso_now_utc()

    print(f"[info] analysis_end={analysis_end.isoformat()} max_repos={args.max_repos}", file=sys.stderr)
    candidates = search_repositories(client, args.max_repos, since_date)
    print(f"[info] candidate repos: {len(candidates)}", file=sys.stderr)

    snapshots: list[RepoSnapshot] = []
    for index, repo in enumerate(candidates, start=1):
        repo_name = repo["repo_name"]
        print(f"[info] ({index}/{len(candidates)}) {repo_name}", file=sys.stderr)
        events = fetch_repo_events(client, repo_name)
        if not events:
            continue
        contributors = fetch_repo_contributors(client, repo_name)
        snapshots.append(build_repo_snapshot(repo, events, analysis_end, contributors))
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    trend_7d = build_trend_rows(snapshots, 7, args.trend_top_n, analysis_end, generated_at)
    trend_14d = build_trend_rows(snapshots, 14, args.trend_top_n, analysis_end, generated_at)
    trend_30d = build_trend_rows(snapshots, 30, args.trend_top_n, analysis_end, generated_at)
    network_30d = build_network(
        snapshots,
        window_days=30,
        max_edges=args.network_max_edges,
        min_shared_count=args.min_shared_count,
        analysis_end=analysis_end,
        generated_at=generated_at,
    )
    network_14d = build_network(
        snapshots,
        window_days=14,
        max_edges=args.network_max_edges,
        min_shared_count=args.min_shared_count,
        analysis_end=analysis_end,
        generated_at=generated_at,
    )
    network_7d = build_network(
        snapshots,
        window_days=7,
        max_edges=args.network_max_edges,
        min_shared_count=args.min_shared_count,
        analysis_end=analysis_end,
        generated_at=generated_at,
    )

    top_repos = {
        "analysis_end_date": analysis_end.isoformat(),
        "generated_at": generated_at,
        "rows": trend_30d["rows"][:20],
    }

    meta = {
        "generated_at": generated_at,
        "analysis_end_date": analysis_end.isoformat(),
        "candidate_repo_count": len(candidates),
        "repo_count_with_events": len(snapshots),
        "event_types": sorted(EVENT_TYPES),
        "windows": list(WINDOWS),
        "source": "github_rest_api",
    }

    out = args.output.rstrip("/")
    write_json(f"{out}/meta.json", meta)
    write_json(f"{out}/trend_7d.json", trend_7d)
    write_json(f"{out}/trend_14d.json", trend_14d)
    write_json(f"{out}/trend_30d.json", trend_30d)
    write_json(f"{out}/network_7d.json", network_7d)
    write_json(f"{out}/network_14d.json", network_14d)
    write_json(f"{out}/network_30d.json", network_30d)
    write_json(f"{out}/top_repos.json", top_repos)

    print("[info] generated static snapshots", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
