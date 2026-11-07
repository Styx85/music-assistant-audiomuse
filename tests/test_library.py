"""Tests for the MA library adapter against a fake ``mass`` object."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace

from music_assistant_models.errors import MusicAssistantError

from audiomuse.library import MassLibraryPort, track_to_seed


@dataclass
class Named:
    name: str


@dataclass
class FakeTrack:
    item_id: str
    name: str
    artists: list[Named] = field(default_factory=list)
    provider: str = "library"


class FakeTracks:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def get_library_item(self, item_id: str) -> FakeTrack:
        self.asked.append(item_id)
        if item_id == "42":
            return FakeTrack("42", "Answer")
        raise MusicAssistantError(f"track not found in library: {item_id}")


def _port() -> tuple[MassLibraryPort, FakeTracks]:
    tracks = FakeTracks()
    mass = SimpleNamespace(music=SimpleNamespace(tracks=tracks))
    return MassLibraryPort(mass, logging.getLogger("test")), tracks


def test_get_track(run) -> None:
    port, tracks = _port()
    assert run(port.get_track("42")).name == "Answer"
    assert run(port.get_track("7")) is None
    assert run(port.get_track("fp_2abc")) is None  # canonical / foreign id: not even asked
    assert tracks.asked == ["42", "7"]


def test_track_to_seed() -> None:
    seed = track_to_seed(FakeTrack("42", "Roc the Mic", [Named("Beanie Sigel"), Named("Freeway")]))
    assert (seed.title, seed.artists, seed.library_id) == (
        "Roc the Mic", ["Beanie Sigel", "Freeway"], "42"
    )
    streaming = track_to_seed(FakeTrack("sp:1", "X", [Named("Y")], provider="spotify--a"))
    assert streaming.library_id is None
