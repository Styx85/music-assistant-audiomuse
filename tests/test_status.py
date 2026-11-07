"""Tests for the settings-page status line."""

from __future__ import annotations

from audiomuse.status import format_status, status_lines


def test_status_with_running_analysis() -> None:
    summary = {
        "content": {
            "total_songs": 1234,
            "clap_indexed": 1200,
            "music_servers": [{"is_default": True, "server_type": "musicassistant"}],
        }
    }
    active = {"task_type": "main_analysis", "details": {"status_message": "Albums 7/50"}}
    lines = status_lines("v3.7.1", summary, active)
    assert [(line.key, line.params) for line in lines] == [
        ("status_summary", ["v3.7.1", "1234", "1200"]),
        ("status_analysis_albums", ["7", "50"]),
    ]
    assert format_status("v3.7.1", summary, active) == (
        "AudioMuse-AI v3.7.1 · 1234 songs analyzed · text search index: 1200 songs · "
        "Analysis running: album 7 of 50"
    )


def test_status_idle_empty_index_wrong_server_and_other_task() -> None:
    summary = {
        "content": {
            "total_songs": 0,
            "music_servers": [{"is_default": True, "server_type": "jellyfin"}],
        }
    }
    active = {"task_type": "server_sweep", "details": {"status_message": "Matching"}}
    lines = status_lines(None, summary, active)
    assert [line.key for line in lines] == [
        "status_summary_no_text_index",
        "status_wrong_server",
        "status_task",
    ]
    assert lines[1].params == ["jellyfin"]
    assert lines[2].text == "Running: server sweep (Matching)"


def test_status_pending_and_error() -> None:
    assert format_status(None, None, None) == "AudioMuse-AI: status pending"
    assert format_status("v1", None, None, "timeout") == "AudioMuse-AI not reachable: timeout"
    assert status_lines("v1", {"content": {"total_songs": "x"}}, None)[0].params[1] == "0"


def test_pick_mood_centroids() -> None:
    from audiomuse.status import pick_mood_centroids

    centroids = {
        "happy": [
            {"index": 0, "mood_score": 0.4, "n_songs": 900},
            {"index": 7, "mood_score": 0.9, "n_songs": 10},
            {"index": 3, "mood_score": 0.9, "n_songs": 50},
        ],
        "sad": [{"index": "x"}],
        "relaxed": [],
    }
    assert pick_mood_centroids(centroids) == {"happy": 3}


def test_status_updated_time_line() -> None:
    lines = status_lines("v1", None, None, "timeout", updated_at="14:35")
    assert [(line.key, line.params) for line in lines] == [
        ("status_unreachable", ["timeout"]),
        ("status_updated", ["14:35"]),
    ]
    assert lines[-1].text == "As of 14:35"
    assert [line.key for line in status_lines("v1", None, None)] == ["status_pending"]
