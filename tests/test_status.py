"""Tests for the settings-page status line."""

from __future__ import annotations

from audiomuse.status import format_status


def test_status_with_running_analysis() -> None:
    summary = {
        "content": {
            "total_songs": 1234,
            "clap_indexed": 1200,
            "music_servers": [{"is_default": True, "server_type": "musicassistant"}],
        }
    }
    active = {"task_type": "main_analysis", "details": {"status_message": "Albums 7/50"}}
    assert format_status("v3.7.1", summary, active) == (
        "AudioMuse-AI v3.7.1 · 1,234 songs analyzed · text search index: 1,200 · "
        "main analysis running: Albums 7/50"
    )


def test_status_idle_empty_and_wrong_server() -> None:
    summary = {
        "content": {
            "total_songs": 0,
            "music_servers": [{"is_default": True, "server_type": "jellyfin"}],
        }
    }
    text = format_status(None, summary, None)
    assert text.startswith("AudioMuse-AI · 0 songs analyzed · text search index: empty")
    assert "default server is jellyfin" in text


def test_status_pending_and_error() -> None:
    assert format_status(None, None, None) == "AudioMuse-AI: status pending"
    assert format_status("v1", None, None, "timeout") == "AudioMuse-AI not reachable: timeout"
    assert "0 songs" in format_status("v1", {"content": {"total_songs": "x"}}, None)
