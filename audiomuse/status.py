"""Status line for the provider settings page, built from AudioMuse-AI's dashboard data."""

from __future__ import annotations

from typing import Any


def format_status(
    version: str | None,
    summary: dict[str, Any] | None,
    active: dict[str, Any] | None,
    error: str | None = None,
) -> str:
    """
    Return a single-line status text.

    :param version: AudioMuse-AI version, if known.
    :param summary: Result of ``/api/dashboard/summary``.
    :param active: Result of ``/api/active_tasks`` (None when idle).
    :param error: Last connection error, if the status could not be fetched.
    """
    if error:
        return f"AudioMuse-AI not reachable: {error}"
    if summary is None:
        return "AudioMuse-AI: status pending"
    content = summary.get("content") or {}
    parts = [f"AudioMuse-AI {version}" if version else "AudioMuse-AI"]
    songs = _int(content.get("total_songs"))
    parts.append(f"{songs:,} songs analyzed")
    clap = _int(content.get("clap_indexed"))
    parts.append(f"text search index: {clap:,}" if clap else "text search index: empty")
    servers = content.get("music_servers") or []
    default = next((s for s in servers if isinstance(s, dict) and s.get("is_default")), None)
    if default and default.get("server_type") != "musicassistant":
        parts.append(f"warning: default server is {default.get('server_type')}")
    if active:
        details = active.get("details") or {}
        message = details.get("status_message") or details.get("message") or active.get("status")
        task = str(active.get("task_type") or "task").replace("_", " ")
        parts.append(f"{task} running: {message}")
    return " · ".join(parts)


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
