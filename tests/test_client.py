"""Tests for the AudioMuse-AI HTTP client against a fake server."""

from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from audiomuse.client import (
    AudioMuseAuthError,
    AudioMuseClient,
    AudioMuseError,
    AudioMuseNotFoundError,
    AudioMuseUnavailableError,
)

from .fake_servers import TOKEN, FakeState, build_audiomuse_app, serve


def test_health_needs_no_token(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            assert await client.health() is True
        assert "Authorization" not in state.requests[0][2]

    run(scenario())


def test_version_sends_bearer_token(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url + "/", api_token=TOKEN)
            assert await client.version() == "1.2.3"

    run(scenario())


def test_wrong_token_raises_auth_error_without_leaking_token(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token="wrong-secret")
            with pytest.raises(AudioMuseAuthError) as err:
                await client.version()
        assert err.value.status == 401
        assert err.value.code == "AUTH_REQUIRED"
        assert "wrong-secret" not in str(err.value)

    run(scenario())


def test_similar_tracks_by_id_parses_rows_and_params(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN, server="Music Assistant")
            rows = await client.similar_tracks(
                item_id="11", n=10, eliminate_duplicates=False, mood_similarity=True
            )
        assert [r.item_id for r in rows] == ["12", "13"]
        assert rows[0].artist == "Band"
        assert rows[0].distance == pytest.approx(0.1)
        assert rows[1].album is None  # "unknown" means no album
        query = state.requests[-1][1]
        assert query == {
            "n": "10",
            "item_id": "11",
            "eliminate_duplicates": "false",
            "mood_similarity": "true",
            "server": "Music Assistant",
        }

    run(scenario())


def test_similar_tracks_by_title_artist(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            await client.similar_tracks(title="Song A", artist="Band", n=5)
        query = state.requests[-1][1]
        assert query == {"n": "5", "title": "Song A", "artist": "Band"}

    run(scenario())


def test_similar_tracks_requires_seed(run) -> None:
    async def scenario() -> None:
        async with aiohttp.ClientSession() as session:
            client = AudioMuseClient(session, "http://127.0.0.1:9")
            with pytest.raises(ValueError):
                await client.similar_tracks(title="only title")

    run(scenario())


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (404, AudioMuseNotFoundError),
        (500, AudioMuseUnavailableError),
        (503, AudioMuseUnavailableError),
        (400, AudioMuseError),
    ],
)
def test_similar_tracks_error_mapping(run, status: int, error: type[Exception]) -> None:
    async def scenario() -> None:
        state = FakeState(similar_status=status)
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            with pytest.raises(error) as err:
                await client.similar_tracks(item_id="11")
        assert err.value.status == status
        assert "Target track not found" in str(err.value)

    run(scenario())


def test_unreachable_server_is_unavailable(run) -> None:
    async def scenario() -> None:
        server = TestServer(web.Application())
        await server.start_server()
        url = str(server.make_url("")).rstrip("/")
        await server.close()
        async with aiohttp.ClientSession() as session:
            client = AudioMuseClient(session, url, api_token=TOKEN, timeout=2)
            with pytest.raises(AudioMuseUnavailableError):
                await client.similar_tracks(item_id="11")

    run(scenario())


def test_non_json_response_is_an_error(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            with pytest.raises(AudioMuseError, match="not JSON"):
                await client._request("GET", "/api/not_json")

    run(scenario())


def test_find_path_and_text_search(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            path = await client.find_path("11", "19", max_steps=8)
            found = await client.text_search("calm piano", limit=1)
        assert [r.item_id for r in path] == ["12", "13"]
        assert [r.item_id for r in found] == ["12"]
        path_query = next(q for p, q, _ in state.requests if p == "/api/find_path")
        assert path_query == {"start_song_id": "11", "end_song_id": "19", "max_steps": "8"}

    run(scenario())


def test_long_token_is_redacted_before_truncation(run) -> None:
    long_token = "SECRET-" + "x" * 500

    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=long_token)
            with pytest.raises(AudioMuseAuthError) as err:
                await client.version()
        assert "SECRET" not in str(err.value)
        assert len(str(err.value)) <= 400

    run(scenario())


def test_dashboard_summary_and_active_task(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            summary = await client.dashboard_summary()
            assert summary["content"]["total_songs"] == 44
            assert await client.active_task() is None  # idle: AudioMuse-AI answers {}
            state.active_task = {"task_id": "t1", "task_type": "main_analysis"}
            assert (await client.active_task())["task_id"] == "t1"

    run(scenario())


def test_moods_anchors_and_radius(run) -> None:
    async def scenario() -> None:
        state = FakeState()
        async with serve(build_audiomuse_app(state)) as (url, session):
            client = AudioMuseClient(session, url, api_token=TOKEN)
            await client.similar_tracks(item_id="11", n=3, radius_similarity=True)
            assert state.requests[-1][1]["radius_similarity"] == "true"
            await client.mood_tracks("happy", 1, n=7)
            assert state.requests[-1][1] == {"mood": "happy", "centroid_index": "1", "n": "7"}
            await client.anchor_tracks(3, n=9)
            assert state.requests[-1][1] == {"anchor_id": "3", "n": "9"}
            assert await client.anchors() == [(3, "Rainy jazz")]
            moods = await client.mood_centroids()
            assert [c["index"] for c in moods["happy"]] == [0, 1]

    run(scenario())
