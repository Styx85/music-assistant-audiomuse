"""Tests for the similar-tracks service with fakes."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from audiomuse.client import AudioMuseNotFoundError, AudioMuseUnavailableError, SimilarTrack
from audiomuse.similar import SeedRef, SimilarOptions, SimilarTracksService


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
