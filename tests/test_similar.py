"""Tests for the similar-tracks service with fakes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from audiomuse.client import AudioMuseNotFoundError, AudioMuseUnavailableError, SimilarTrack
from audiomuse.similar import SeedRef, SimilarOptions, SimilarTracksService, with_fallbacks


def _row(item_id: str) -> SimilarTrack:
    return SimilarTrack(item_id, f"T{item_id}", "A", None, None, 0.1)


class FakeClient:
    """Answers per seed kind; records calls."""

    def __init__(self, by_id=None, by_title=None, error: Exception | None = None):
        self.by_id = by_id
        self.by_title = by_title
        self.error = error
        self.calls: list[dict] = []

    async def similar_tracks(self, **kwargs) -> list[SimilarTrack]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        result = self.by_id if "item_id" in kwargs else self.by_title
        if isinstance(result, Exception):
            raise result
        return result or []


@dataclass(frozen=True)
class FakeTrack:
    item_id: str


class FakeLibrary:
    def __init__(self, known: set[str]):
        self.known = known
        self.asked: list[str] = []

    async def get_track(self, item_id: str) -> FakeTrack | None:
        self.asked.append(item_id)
        return FakeTrack(item_id) if item_id in self.known else None


def test_by_library_id_drops_seed_duplicates_and_missing(run) -> None:
    client = FakeClient(by_id=[_row("1"), _row("2"), _row("2"), _row("404"), _row("3"), _row("4")])
    library = FakeLibrary({"2", "3", "4"})
    service = SimilarTracksService(client, library)
    seed = SeedRef("Seed", ["A"], library_id="1")
    options = SimilarOptions(eliminate_duplicates=True, mood_similarity=False)

    result = run(service.similar_tracks(seed, limit=2, options=options))

    assert [t.item_id for t in result] == ["2", "3"]  # seed, duplicate and 404 skipped
    assert client.calls == [
        {"item_id": "1", "n": 5, "eliminate_duplicates": True, "mood_similarity": False}
    ]
    assert "1" not in library.asked  # the seed is never loaded
    assert library.asked.count("2") == 1
    stats = service.last_stats
    assert (stats.seed_by_id, stats.received, stats.unresolved, stats.returned) == (True, 6, 1, 2)


def test_unknown_id_falls_back_to_title_artist(run) -> None:
    client = FakeClient(by_id=AudioMuseNotFoundError("nope", 404), by_title=[_row("7")])
    service = SimilarTracksService(client, FakeLibrary({"7"}))
    result = run(service.similar_tracks(SeedRef("Song", ["Band", "Guest"], library_id="1"), 5))
    assert [t.item_id for t in result] == ["7"]
    assert client.calls[1]["title"] == "Song" and client.calls[1]["artist"] == "Band"
    assert service.last_stats.used_title_artist is True


def test_streaming_seed_without_library_id_uses_fallback(run) -> None:
    client = FakeClient(by_title=[_row("7")])
    service = SimilarTracksService(client, FakeLibrary({"7"}))
    result = run(service.similar_tracks(SeedRef("Song", ["Band"]), 5))
    assert [t.item_id for t in result] == ["7"]
    assert "item_id" not in client.calls[0]


def test_fallback_disabled(run) -> None:
    client = FakeClient(by_id=AudioMuseNotFoundError("nope", 404), by_title=[_row("7")])
    service = SimilarTracksService(client, FakeLibrary({"7"}))
    options = SimilarOptions(title_artist_fallback=False)
    assert run(service.similar_tracks(SeedRef("S", ["A"], library_id="1"), 5, options)) == []
    assert len(client.calls) == 1
    assert run(service.similar_tracks(SeedRef("S", ["A"]), 5, options)) == []
    assert len(client.calls) == 1  # nothing to ask without id and fallback


def test_both_unknown_returns_empty(run) -> None:
    not_found = AudioMuseNotFoundError("nope", 404)
    client = FakeClient(by_id=not_found, by_title=not_found)
    service = SimilarTracksService(client, FakeLibrary(set()))
    assert run(service.similar_tracks(SeedRef("S", ["A"], library_id="1"), 5)) == []


def test_unavailable_propagates(run) -> None:
    client = FakeClient(error=AudioMuseUnavailableError("down"))
    service = SimilarTracksService(client, FakeLibrary(set()))
    with pytest.raises(AudioMuseUnavailableError):
        run(service.similar_tracks(SeedRef("S", ["A"], library_id="1"), 5))


def test_limit_zero_and_request_cap(run) -> None:
    client = FakeClient(by_id=[])
    service = SimilarTracksService(client, FakeLibrary(set()))
    assert run(service.similar_tracks(SeedRef("S", ["A"], library_id="1"), 0)) == []
    assert client.calls == []
    run(service.similar_tracks(SeedRef("S", ["A"], library_id="1"), 500))
    assert client.calls[0]["n"] == 200


class SeedClient:
    """Answers per seed id; text search returns fixed rows or raises."""

    def __init__(self, by_seed, text_rows=None, text_error=None):
        self.by_seed = by_seed
        self.text_rows = text_rows or []
        self.text_error = text_error
        self.calls: list[dict] = []

    async def similar_tracks(self, **kwargs):
        self.calls.append(kwargs)
        result = self.by_seed.get(kwargs["item_id"], [])
        if isinstance(result, Exception):
            raise result
        return result

    async def text_search(self, query, limit=25):
        self.calls.append({"query": query, "limit": limit})
        if self.text_error:
            raise self.text_error
        return self.text_rows


def test_inspired_by_merges_seeds_in_order_and_skips_unknown(run) -> None:
    client = SeedClient(
        {
            "1": [_row("10"), _row("2"), _row("11")],
            "2": AudioMuseNotFoundError("nope", 404),
            "3": [_row("11"), _row("12"), _row("1")],
        }
    )
    service = SimilarTracksService(client, FakeLibrary({"10", "11", "12"}))
    seeds = [SeedRef("a", ["A"], "1"), SeedRef("b", ["B"], "2"), SeedRef("s", ["S"]),
             SeedRef("c", ["C"], "3")]
    result = run(service.inspired_by(seeds, limit=10, per_seed=5))
    assert [t.item_id for t in result] == ["10", "11", "12"]  # seeds 1-3 never returned
    assert [c["item_id"] for c in client.calls] == ["1", "2", "3"]
    assert client.calls[0]["n"] == 6


def test_inspired_by_limits_and_handles_no_seeds(run) -> None:
    client = SeedClient({"1": [_row(str(i)) for i in range(10, 30)]})
    service = SimilarTracksService(client, FakeLibrary({str(i) for i in range(10, 30)}))
    assert len(run(service.inspired_by([SeedRef("a", ["A"], "1")], limit=3, per_seed=20))) == 3
    assert run(service.inspired_by([SeedRef("s", ["S"])], limit=3, per_seed=5)) == []
    assert run(service.inspired_by([SeedRef("a", ["A"], "1")], limit=0, per_seed=5)) == []


def test_text_search(run) -> None:
    client = SeedClient({}, text_rows=[_row("7"), _row("7"), _row("404"), _row("8")])
    service = SimilarTracksService(client, FakeLibrary({"7", "8"}))
    assert [t.item_id for t in run(service.text_search("  calm piano ", 5))] == ["7", "8"]
    assert client.calls[0] == {"query": "calm piano", "limit": 10}
    assert run(service.text_search("   ", 5)) == []


def test_text_search_errors_propagate_so_they_are_not_cached(run) -> None:
    client = SeedClient({}, text_error=AudioMuseUnavailableError("CLAP cache not loaded", 503))
    service = SimilarTracksService(client, FakeLibrary({"7"}))
    with pytest.raises(AudioMuseUnavailableError):
        run(service.text_search("piano", 5))


def test_inspired_by_keeps_partial_results_on_errors_and_timeouts(run) -> None:
    class SlowClient(SeedClient):
        async def similar_tracks(self, **kwargs):
            if kwargs["item_id"] == "slow":
                await asyncio.sleep(1)
            return await super().similar_tracks(**kwargs)

    client = SlowClient({"1": [_row("10")], "2": AudioMuseUnavailableError("down", 500)})
    service = SimilarTracksService(client, FakeLibrary({"10"}))
    seeds = [SeedRef("s", ["S"], "slow"), SeedRef("a", ["A"], "1"), SeedRef("b", ["B"], "2")]
    result = run(service.inspired_by(seeds, limit=5, per_seed=5, timeout=0.05))
    assert [t.item_id for t in result] == ["10"]


def test_inspired_by_raises_when_every_seed_fails(run) -> None:
    client = SeedClient({"1": AudioMuseUnavailableError("down", 500)})
    service = SimilarTracksService(client, FakeLibrary(set()))
    with pytest.raises(AudioMuseUnavailableError):
        run(service.inspired_by([SeedRef("a", ["A"], "1")], limit=5, per_seed=5))


def test_with_fallbacks_prefers_audiomuse(run) -> None:
    async def primary():
        return ["a"]

    async def never():
        raise AssertionError("must not be asked")

    assert run(with_fallbacks(primary, [("sonic", never)])) == (["a"], "audiomuse", None)


def test_with_fallbacks_walks_the_ranking_in_order(run) -> None:
    asked: list[str] = []

    def source(name, result):
        async def _ask():
            asked.append(name)
            return result

        return (name, _ask)

    async def failing():
        raise AudioMuseUnavailableError("index empty", 503)

    tracks, source_name, error = run(
        with_fallbacks(
            failing, [source("sonic", []), source("spotify", ["s"]), source("lastfm", ["l"])]
        )
    )
    assert (tracks, source_name) == (["s"], "spotify")
    assert isinstance(error, AudioMuseUnavailableError)
    assert asked == ["sonic", "spotify"]


def test_with_fallbacks_keeps_error_when_nothing_answers(run) -> None:
    async def failing():
        raise AudioMuseUnavailableError("down", 503)

    async def empty():
        return []

    with pytest.raises(AudioMuseUnavailableError):
        run(with_fallbacks(failing, [("sonic", empty)]))
    with pytest.raises(AudioMuseUnavailableError):
        run(with_fallbacks(failing, []))
    assert run(with_fallbacks(empty, [])) == ([], "none", None)
