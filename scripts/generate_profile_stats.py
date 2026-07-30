"""Generate monochrome GitHub profile stat cards.

This module intentionally keeps the runtime dependency surface small:
it uses only the Python standard library and the public GitHub REST API.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from time import sleep
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import os
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "assets" / "profile-stats"
API_ROOT = "https://api.github.com"
LOCAL_TZ = ZoneInfo("America/Detroit")
API_TIMEOUT_SECONDS = 15
API_MAX_RETRIES = 3
MAX_PAGE_SIZE = 100
GITHUB_USERNAME_RE = re.compile(r"^[A-Za-z\d](?:[A-Za-z\d]|-(?=[A-Za-z\d])){0,38}$")

CARD_BG = "#050505"
CARD_BORDER = "#232323"
TEXT_PRIMARY = "#F7F7F7"
TEXT_SECONDARY = "#B8B8B8"
TEXT_MUTED = "#8E8E8E"
GRID = "#242424"
BAR_PRIMARY = "#F7F7F7"
BAR_SECONDARY = "#CFCFCF"
FONT_STACK = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace"


def validate_username(username: str) -> str:
    """Return a validated GitHub username or raise a ValueError."""

    if not GITHUB_USERNAME_RE.fullmatch(username):
        raise ValueError(f"Invalid GitHub username: {username!r}")
    return username


USERNAME = validate_username(os.environ.get("PROFILE_USERNAME", "MusammatA"))
TOKEN = os.environ.get("GITHUB_TOKEN", "")


class GitHubApiError(RuntimeError):
    """Raised when the GitHub API request cannot complete safely."""


def build_headers() -> dict[str, str]:
    """Construct the headers used for GitHub REST API requests."""

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def github_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Fetch and decode a JSON payload from the GitHub API.

    Retries are limited to transient transport errors and 5xx responses.
    """

    if not path.startswith("/"):
        raise ValueError(f"API path must start with '/': {path!r}")

    query = f"?{urlencode(params)}" if params else ""
    url = f"{API_ROOT}{path}{query}"
    request = Request(url, headers=build_headers())

    for attempt in range(1, API_MAX_RETRIES + 1):
        try:
            with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code in {500, 502, 503, 504} and attempt < API_MAX_RETRIES:
                sleep(attempt)
                continue
            if exc.code == 403:
                raise GitHubApiError(
                    "GitHub API access was denied or rate-limited. "
                    "Try again later or provide GITHUB_TOKEN."
                ) from exc
            raise GitHubApiError(f"GitHub API request failed: {exc.code} {exc.reason}") from exc
        except URLError as exc:
            if attempt < API_MAX_RETRIES:
                sleep(attempt)
                continue
            raise GitHubApiError(f"Network error while calling GitHub API: {exc.reason}") from exc

    raise GitHubApiError("GitHub API request retries were exhausted")


def paginated_get(path: str, params: dict[str, Any]) -> list[Any]:
    """Retrieve a list response across paginated GitHub API endpoints."""

    items: list[Any] = []
    page = 1
    while True:
        payload = github_get(path, {**params, "page": page, "per_page": MAX_PAGE_SIZE})
        if not isinstance(payload, list):
            raise GitHubApiError(f"Expected list payload from {path!r}")
        if not payload:
            break
        items.extend(payload)
        if len(payload) < MAX_PAGE_SIZE:
            break
        page += 1
    return items


def fetch_user() -> dict[str, Any]:
    payload = github_get(f"/users/{USERNAME}")
    if not isinstance(payload, dict):
        raise GitHubApiError("User payload was not an object")
    return payload


def fetch_repos() -> list[dict[str, Any]]:
    repos = paginated_get(
        f"/users/{USERNAME}/repos",
        {
            "type": "owner",
            "sort": "updated",
        },
    )
    return [repo for repo in repos if isinstance(repo, dict) and not repo.get("fork")]


def fetch_repo_languages(repo: dict[str, Any]) -> dict[str, int]:
    owner = repo.get("owner", {}).get("login")
    name = repo.get("name")
    if not owner or not name:
        return {}

    payload = github_get(f"/repos/{owner}/{name}/languages")
    if not isinstance(payload, dict):
        raise GitHubApiError(f"Language payload for {owner}/{name} was not an object")
    return {str(language): int(byte_count) for language, byte_count in payload.items()}


def collect_language_totals(language_maps: Iterable[dict[str, int]]) -> list[tuple[str, int]]:
    totals: Counter[str] = Counter()
    for language_map in language_maps:
        for language, byte_count in language_map.items():
            totals[language] += int(byte_count)
    return totals.most_common()


def aggregate_languages(repos: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return collect_language_totals(fetch_repo_languages(repo) for repo in repos)


def month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    serial = year * 12 + (month - 1) + delta
    return serial // 12, serial % 12 + 1


def month_bins(count: int = 12, reference: datetime | None = None) -> list[tuple[int, int]]:
    if count < 1:
        raise ValueError("count must be at least 1")
    current = reference or datetime.now(LOCAL_TZ)
    start_year, start_month = month_shift(current.year, current.month, -(count - 1))
    return [month_shift(start_year, start_month, idx) for idx in range(count)]


def build_month_labels(bins: Iterable[tuple[int, int]]) -> list[str]:
    return [datetime(year, month, 1).strftime("%b") for year, month in bins]


def fetch_repo_commits_since(repo: dict[str, Any], since_iso: str) -> list[dict[str, Any]]:
    owner = repo.get("owner", {}).get("login")
    name = repo.get("name")
    default_branch = repo.get("default_branch")
    if not owner or not name or not default_branch:
        return []

    commits: list[dict[str, Any]] = []
    page = 1
    while True:
        try:
            payload = github_get(
                f"/repos/{owner}/{name}/commits",
                {
                    "sha": default_branch,
                    "since": since_iso,
                    "page": page,
                },
            )
        except GitHubApiError as exc:
            root_exc = exc.__cause__
            if isinstance(root_exc, HTTPError) and root_exc.code in {409, 422}:
                return commits
            raise

        if not isinstance(payload, list):
            raise GitHubApiError(f"Commit payload for {owner}/{name} was not a list")
        if not payload:
            break
        commits.extend(payload)
        if len(payload) < MAX_PAGE_SIZE:
            break
        page += 1
    return commits


def count_commit_dates_by_month(
    commit_datetimes: Iterable[datetime],
    bins: list[tuple[int, int]],
) -> list[int]:
    counts = Counter({key: 0 for key in bins})
    for commit_datetime in commit_datetimes:
        key = (commit_datetime.year, commit_datetime.month)
        if key in counts:
            counts[key] += 1
    return [counts[key] for key in bins]


def monthly_commit_counts(repos: list[dict[str, Any]]) -> tuple[list[str], list[int]]:
    bins = month_bins(12)
    first_year, first_month = bins[0]
    since = datetime(first_year, first_month, 1, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    since_iso = since.isoformat().replace("+00:00", "Z")

    commit_datetimes: list[datetime] = []
    for repo in repos:
        for commit in fetch_repo_commits_since(repo, since_iso):
            raw_date = commit.get("commit", {}).get("author", {}).get("date")
            if not raw_date:
                continue
            commit_datetimes.append(
                datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            )

    return build_month_labels(bins), count_commit_dates_by_month(commit_datetimes, bins)


def format_int(value: int) -> str:
    return f"{value:,}"


def render_card_shell(
    title: str,
    width: int = 860,
    height: int = 320,
    title_size: int = 24,
) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"  <title>{escape(title)}</title>",
        f"  <desc>{escape(title)}</desc>",
        f'  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="28" fill="{CARD_BG}" stroke="{CARD_BORDER}" stroke-width="2"/>',
        f'  <text x="36" y="60" fill="{TEXT_PRIMARY}" font-family="{FONT_STACK}" font-size="{title_size}" font-weight="700">{escape(title)}</text>',
    ]


def save_svg(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_overview(user: dict[str, Any], repos: list[dict[str, Any]], height: int) -> None:
    total_stars = sum(int(repo.get("stargazers_count", 0)) for repo in repos)
    total_forks = sum(int(repo.get("forks_count", 0)) for repo in repos)
    total_open_issues = sum(int(repo.get("open_issues_count", 0)) for repo in repos)
    lines = render_card_shell("Overall contribution metrics", height=height)
    metrics = [
        ("Public repos", format_int(int(user.get("public_repos", 0)))),
        ("Followers", format_int(int(user.get("followers", 0)))),
        ("Following", format_int(int(user.get("following", 0)))),
        ("Total stars", format_int(total_stars)),
        ("Total forks", format_int(total_forks)),
        ("Open issues", format_int(total_open_issues)),
    ]
    block_w = 214
    block_h = 88
    start_x = 36
    start_y = 96
    gap_x = 22
    gap_y = 20

    for idx, (label, value) in enumerate(metrics):
        col = idx % 3
        row = idx // 3
        x = start_x + col * (block_w + gap_x)
        y = start_y + row * (block_h + gap_y)
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{block_w}" height="{block_h}" rx="18" fill="#0D0D0D" stroke="{GRID}"/>'
        )
        lines.append(
            f'  <text x="{x + 18}" y="{y + 34}" fill="{TEXT_SECONDARY}" font-family="{FONT_STACK}" font-size="13">{escape(label)}</text>'
        )
        lines.append(
            f'  <text x="{x + 18}" y="{y + 68}" fill="{TEXT_PRIMARY}" font-family="{FONT_STACK}" font-size="34" font-weight="700">{escape(value)}</text>'
        )

    lines.append("</svg>")
    save_svg(OUTPUT_DIR / "overview.svg", lines)


def render_languages(language_totals: list[tuple[str, int]]) -> None:
    total_bytes = sum(byte_count for _, byte_count in language_totals) or 1
    count = max(1, len(language_totals))
    height = max(360, 102 + count * 42)
    lines = render_card_shell("Language distribution", height=height)
    chart_x = 36
    chart_y = 108
    bar_w = 520
    bar_h = 16
    row_gap = 42
    palette = [
        BAR_PRIMARY,
        BAR_SECONDARY,
        "#B5B5B5",
        "#9B9B9B",
        "#7F7F7F",
        "#6C6C6C",
        "#585858",
        "#454545",
    ]

    for idx, (language, byte_count) in enumerate(language_totals):
        y = chart_y + idx * row_gap
        width = max(18, round((byte_count / total_bytes) * bar_w))
        percent = (byte_count / total_bytes) * 100
        fill = palette[min(idx, len(palette) - 1)]
        lines.append(
            f'  <text x="{chart_x}" y="{y - 10}" fill="{TEXT_SECONDARY}" font-family="{FONT_STACK}" font-size="13">{escape(language)}</text>'
        )
        lines.append(
            f'  <rect x="{chart_x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="9" fill="#111111" stroke="{GRID}"/>'
        )
        lines.append(
            f'  <rect x="{chart_x}" y="{y}" width="{width}" height="{bar_h}" rx="9" fill="{fill}"/>'
        )
        lines.append(
            f'  <text x="{chart_x + bar_w + 18}" y="{y + 13}" fill="{TEXT_PRIMARY}" font-family="{FONT_STACK}" font-size="13">{percent:0.1f}%</text>'
        )

    lines.append("</svg>")
    save_svg(OUTPUT_DIR / "languages.svg", lines)


def render_commits_by_month(month_labels: list[str], monthly_counts: list[int]) -> None:
    lines = render_card_shell("Commits by month", width=860, height=360, title_size=22)
    chart_x = 68
    chart_y = 290
    chart_h = 176
    chart_w = 736
    max_count = max(monthly_counts) or 1

    for tick in range(5):
        y = chart_y - round((tick / 4) * chart_h)
        value = round((tick / 4) * max_count)
        lines.append(
            f'  <line x1="{chart_x}" y1="{y}" x2="{chart_x + chart_w}" y2="{y}" stroke="{GRID}" stroke-width="1"/>'
        )
        lines.append(
            f'  <text x="{chart_x - 14}" y="{y + 5}" fill="{TEXT_MUTED}" text-anchor="end" font-family="{FONT_STACK}" font-size="12">{value}</text>'
        )

    step_x = chart_w / max(1, len(monthly_counts) - 1)
    points: list[tuple[float, float]] = []
    for idx, count in enumerate(monthly_counts):
        x = chart_x + idx * step_x
        y = chart_y - ((count / max_count) * (chart_h - 10))
        points.append((x, y))

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    lines.append(
        f'  <polyline points="{polyline}" fill="none" stroke="{BAR_PRIMARY}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
    )

    for idx, ((x, y), label) in enumerate(zip(points, month_labels)):
        fill = BAR_PRIMARY if idx == len(points) - 1 else BAR_SECONDARY
        radius = 5.5 if idx == len(points) - 1 else 4.5
        lines.append(
            f'  <circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{fill}" stroke="{CARD_BG}" stroke-width="2"/>'
        )
        lines.append(
            f'  <text x="{x:.2f}" y="{chart_y + 28}" text-anchor="middle" fill="{TEXT_MUTED}" font-family="{FONT_STACK}" font-size="12">{escape(label)}</text>'
        )

    lines.append(
        f'  <line x1="{chart_x}" y1="{chart_y}" x2="{chart_x + chart_w}" y2="{chart_y}" stroke="{TEXT_MUTED}" stroke-width="1.5"/>'
    )
    lines.append("</svg>")
    save_svg(OUTPUT_DIR / "activity.svg", lines)


def main() -> None:
    user = fetch_user()
    repos = fetch_repos()
    languages = aggregate_languages(repos)
    month_labels, month_counts = monthly_commit_counts(repos)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    top_card_height = max(360, 102 + len(languages) * 42)
    render_overview(user, repos, top_card_height)
    render_languages(languages or [("No language data yet", 1)])
    render_commits_by_month(month_labels, month_counts)


if __name__ == "__main__":
    main()
