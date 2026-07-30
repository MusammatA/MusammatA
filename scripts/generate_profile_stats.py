from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "assets" / "profile-stats"
API_ROOT = "https://api.github.com"
USERNAME = os.environ.get("PROFILE_USERNAME", "MusammatA")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
LOCAL_TZ = ZoneInfo("America/Detroit")

CARD_BG = "#050505"
CARD_BORDER = "#232323"
TEXT_PRIMARY = "#F7F7F7"
TEXT_SECONDARY = "#B8B8B8"
TEXT_MUTED = "#8E8E8E"
GRID = "#242424"
BAR_PRIMARY = "#F7F7F7"
BAR_SECONDARY = "#CFCFCF"
BAR_TERTIARY = "#9A9A9A"


def github_get(path: str, params: dict[str, Any] | None = None) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{API_ROOT}{path}{query}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = Request(
        url,
        headers=headers,
    )
    with urlopen(request) as response:
        return json.load(response)


def paginated_get(path: str, params: dict[str, Any]) -> list[Any]:
    items: list[Any] = []
    page = 1
    while True:
        payload = github_get(path, {**params, "page": page})
        if not payload:
            break
        items.extend(payload)
        if len(payload) < params.get("per_page", 100):
            break
        page += 1
    return items


def fetch_user() -> dict[str, Any]:
    return github_get(f"/users/{USERNAME}")


def fetch_repos() -> list[dict[str, Any]]:
    repos = paginated_get(
        f"/users/{USERNAME}/repos",
        {
            "type": "owner",
            "sort": "updated",
            "per_page": 100,
        },
    )
    return [repo for repo in repos if not repo.get("fork")]


def fetch_repo_languages(repo: dict[str, Any]) -> dict[str, int]:
    languages_url = repo.get("languages_url", "")
    if not languages_url.startswith(API_ROOT):
        return {}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = Request(
        languages_url,
        headers=headers,
    )
    with urlopen(request) as response:
        return json.load(response)


def fetch_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for page in range(1, 4):
        payload = github_get(
            f"/users/{USERNAME}/events/public",
            {"per_page": 100, "page": page},
        )
        if not payload:
            break
        events.extend(payload)
        if len(payload) < 100:
            break
    return events


def aggregate_languages(repos: list[dict[str, Any]]) -> list[tuple[str, int]]:
    totals: Counter[str] = Counter()
    for repo in repos:
        for language, byte_count in fetch_repo_languages(repo).items():
            totals[language] += int(byte_count)
    return totals.most_common(5)


def recent_push_hours(events: list[dict[str, Any]]) -> tuple[list[int], int]:
    hourly = [0] * 24
    push_count = 0
    for event in events:
        if event.get("type") != "PushEvent":
            continue
        created_at = event.get("created_at")
        if not created_at:
            continue
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        commit_count = len(event.get("payload", {}).get("commits", [])) or 1
        hourly[dt.hour] += commit_count
        push_count += 1
    return hourly, push_count


def format_int(value: int) -> str:
    return f"{value:,}"


def render_card_shell(title: str, subtitle: str, width: int = 860, height: int = 320) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'  <title>{escape(title)}</title>',
        f'  <desc>{escape(subtitle)}</desc>',
        f'  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="28" fill="{CARD_BG}" stroke="{CARD_BORDER}" stroke-width="2"/>',
        f'  <text x="36" y="58" fill="{TEXT_PRIMARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="26" font-weight="700">{escape(title)}</text>',
        f'  <text x="36" y="88" fill="{TEXT_SECONDARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="14">{escape(subtitle)}</text>',
    ]


def save_svg(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_overview(user: dict[str, Any], repos: list[dict[str, Any]]) -> None:
    total_stars = sum(int(repo.get("stargazers_count", 0)) for repo in repos)
    total_forks = sum(int(repo.get("forks_count", 0)) for repo in repos)
    total_watchers = sum(int(repo.get("watchers_count", 0)) for repo in repos)
    refreshed = datetime.now(LOCAL_TZ).strftime("%b %d, %Y")
    lines = render_card_shell(
        "Overall contribution metrics",
        f"Auto-updated from public GitHub data | Refreshed {refreshed}",
    )
    metrics = [
        ("Public repos", format_int(int(user.get("public_repos", 0)))),
        ("Followers", format_int(int(user.get("followers", 0)))),
        ("Total stars", format_int(total_stars)),
        ("Total forks", format_int(total_forks)),
        ("Watching", format_int(total_watchers)),
        ("Following", format_int(int(user.get("following", 0)))),
    ]
    block_w = 242
    block_h = 76
    start_x = 36
    start_y = 124
    gap_x = 22
    gap_y = 20
    for idx, (label, value) in enumerate(metrics):
        col = idx % 3
        row = idx // 3
        x = start_x + col * (block_w + gap_x)
        y = start_y + row * (block_h + gap_y)
        lines.append(f'  <rect x="{x}" y="{y}" width="{block_w}" height="{block_h}" rx="18" fill="#0D0D0D" stroke="{GRID}"/>')
        lines.append(
            f'  <text x="{x + 18}" y="{y + 32}" fill="{TEXT_SECONDARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="13">{escape(label)}</text>'
        )
        lines.append(
            f'  <text x="{x + 18}" y="{y + 62}" fill="{TEXT_PRIMARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="28" font-weight="700">{escape(value)}</text>'
        )
    lines.append("</svg>")
    save_svg(OUTPUT_DIR / "overview.svg", lines)


def render_languages(language_totals: list[tuple[str, int]]) -> None:
    total_bytes = sum(byte_count for _, byte_count in language_totals) or 1
    lines = render_card_shell(
        "Language distribution",
        "Based on owned repositories | Top languages by bytes of code",
    )
    chart_x = 36
    chart_y = 126
    bar_w = 520
    bar_h = 18
    row_gap = 32
    palette = [BAR_PRIMARY, BAR_SECONDARY, "#B5B5B5", "#9B9B9B", "#7F7F7F"]
    for idx, (language, byte_count) in enumerate(language_totals):
        y = chart_y + idx * row_gap
        width = max(18, round((byte_count / total_bytes) * bar_w))
        percent = (byte_count / total_bytes) * 100
        lines.append(f'  <text x="{chart_x}" y="{y - 8}" fill="{TEXT_SECONDARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="13">{escape(language)}</text>')
        lines.append(f'  <rect x="{chart_x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="9" fill="#111111" stroke="{GRID}"/>')
        lines.append(f'  <rect x="{chart_x}" y="{y}" width="{width}" height="{bar_h}" rx="9" fill="{palette[idx]}"/>')
        lines.append(
            f'  <text x="{chart_x + bar_w + 18}" y="{y + 14}" fill="{TEXT_PRIMARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="13">{percent:0.1f}%</text>'
        )
    lines.append("</svg>")
    save_svg(OUTPUT_DIR / "languages.svg", lines)


def render_activity(hourly_counts: list[int], push_events: int) -> None:
    now = datetime.now(LOCAL_TZ)
    offset = now.utcoffset() or timedelta()
    hours_offset = int(offset.total_seconds() // 3600)
    subtitle = f"Recent public push activity by hour | America/Detroit (UTC {hours_offset:+d})"
    lines = render_card_shell("Recent coding activity", subtitle, width=860, height=360)
    chart_x = 52
    chart_y = 284
    chart_h = 180
    chart_w = 760
    max_count = max(hourly_counts) or 1
    for tick in range(5):
        y = chart_y - round((tick / 4) * chart_h)
        value = round((tick / 4) * max_count)
        lines.append(f'  <line x1="{chart_x}" y1="{y}" x2="{chart_x + chart_w}" y2="{y}" stroke="{GRID}" stroke-width="1"/>')
        lines.append(
            f'  <text x="{chart_x - 12}" y="{y + 5}" fill="{TEXT_MUTED}" text-anchor="end" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="12">{value}</text>'
        )
    bar_gap = 6
    bar_w = (chart_w - (23 * bar_gap)) / 24
    for hour, count in enumerate(hourly_counts):
        height = round((count / max_count) * (chart_h - 8))
        x = chart_x + hour * (bar_w + bar_gap)
        y = chart_y - height
        fill = BAR_PRIMARY if 8 <= hour <= 22 else BAR_TERTIARY
        lines.append(f'  <rect x="{x:.2f}" y="{y}" width="{bar_w:.2f}" height="{height}" rx="6" fill="{fill}"/>')
        if hour in {0, 6, 12, 18, 23}:
            lines.append(
                f'  <text x="{x + (bar_w / 2):.2f}" y="{chart_y + 26}" text-anchor="middle" fill="{TEXT_MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="12">{hour}</text>'
            )
    lines.append(f'  <line x1="{chart_x}" y1="{chart_y}" x2="{chart_x + chart_w}" y2="{chart_y}" stroke="{TEXT_MUTED}" stroke-width="1.5"/>')
    lines.append(
        f'  <text x="36" y="332" fill="{TEXT_SECONDARY}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="13">Derived from the latest {push_events} public push events</text>'
    )
    lines.append("</svg>")
    save_svg(OUTPUT_DIR / "activity.svg", lines)


def main() -> None:
    user = fetch_user()
    repos = fetch_repos()
    languages = aggregate_languages(repos)
    events = fetch_events()
    hourly, push_events = recent_push_hours(events)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    render_overview(user, repos)
    render_languages(languages or [("No language data yet", 1)])
    render_activity(hourly, push_events)


if __name__ == "__main__":
    main()
