"""Status line for the provider settings page, built from AudioMuse-AI's dashboard data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_ALBUMS_RE = re.compile(r"Albums\s+(\d+)\s*/\s*(\d+)")


@dataclass(frozen=True, slots=True)
class StatusLine:
    """One translatable status line: translation slug, placeholder values, English fallback."""

    key: str
    params: list[str] = field(default_factory=list)
    fallback: str = ""

    @property
    def text(self) -> str:
        """Return the English text with the placeholders filled in."""
        return self.fallback.format(*self.params)


def status_lines(
    version: str | None,
    summary: dict[str, Any] | None,
    active: dict[str, Any] | None,
    error: str | None = None,
) -> list[StatusLine]:
    """
    Return the status as translatable lines for the provider settings page.

    :param version: AudioMuse-AI version, if known.
    :param summary: Result of ``/api/dashboard/summary``.
    :param active: Result of ``/api/active_tasks`` (None when idle).
    :param error: Last connection error, if the status could not be fetched.
    """
    if error:
        return [StatusLine("status_unreachable", [error], "AudioMuse-AI not reachable: {0}")]
    if summary is None:
        return [StatusLine("status_pending", [], "AudioMuse-AI: status pending")]
    content = summary.get("content") or {}
    songs = str(_int(content.get("total_songs")))
    clap = _int(content.get("clap_indexed"))
    name = version or "?"
    if clap:
        lines = [
            StatusLine(
                "status_summary",
                [name, songs, str(clap)],
                "AudioMuse-AI {0} · {1} songs analyzed · text search index: {2} songs",
            )
        ]
    else:
        lines = [
            StatusLine(
                "status_summary_no_text_index",
                [name, songs],
                "AudioMuse-AI {0} · {1} songs analyzed · text search index: empty",
            )
        ]
    servers = content.get("music_servers") or []
    default = next((s for s in servers if isinstance(s, dict) and s.get("is_default")), None)
    if default and default.get("server_type") != "musicassistant":
        lines.append(
            StatusLine(
                "status_wrong_server",
                [str(default.get("server_type"))],
                "Warning: AudioMuse-AI's default server is {0}, not Music Assistant",
            )
        )
    if active:
        details = active.get("details") or {}
        message = str(
            details.get("status_message") or details.get("message") or active.get("status") or ""
        )
        if match := _ALBUMS_RE.search(message):
            lines.append(
                StatusLine(
                    "status_analysis_albums",
                    [match.group(1), match.group(2)],
                    "Analysis running: album {0} of {1}",
                )
            )
        else:
            task = str(active.get("task_type") or "task").replace("_", " ")
            lines.append(StatusLine("status_task", [task, message], "Running: {0} ({1})"))
    return lines


def format_status(
    version: str | None,
    summary: dict[str, Any] | None,
    active: dict[str, Any] | None,
    error: str | None = None,
) -> str:
    """
    Return the status as one English line (for logs).

    :param version: AudioMuse-AI version, if known.
    :param summary: Result of ``/api/dashboard/summary``.
    :param active: Result of ``/api/active_tasks`` (None when idle).
    :param error: Last connection error, if the status could not be fetched.
    """
    return " · ".join(line.text for line in status_lines(version, summary, active, error))


def pick_mood_centroids(centroids: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """
    Choose one centroid per mood: the one AudioMuse-AI rates as most typical for it.

    :param centroids: Result of ``/api/mood_centroids`` (mood -> list of centroid metadata).
    """
    chosen: dict[str, int] = {}
    for mood, items in centroids.items():
        best = max(
            (c for c in items if isinstance(c.get("index"), int)),
            key=lambda c: (_float(c.get("mood_score")), _int(c.get("n_songs"))),
            default=None,
        )
        if best is not None:
            chosen[mood] = int(best["index"])
    return chosen


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
