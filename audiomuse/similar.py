"""
Similar-tracks logic, independent of Music Assistant.

AudioMuse-AI analyzes the Music Assistant library through its ``musicassistant`` server
type, so its track ids are MA library track ids. The MA adapter supplies a
:class:`LibraryPort` that loads library tracks by id; everything else lives here so it can
be tested with fakes.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from .client import AudioMuseClient, AudioMuseNotFoundError
from .constants import MAX_REQUEST_N, OVERFETCH_FACTOR, RESOLVE_CONCURRENCY

T = TypeVar("T")


class LibraryPort(Protocol[T]):
    """Access to the MA library, implemented by the MA adapter."""

    async def get_track(self, item_id: str) -> T | None:
        """
        Return the MA library track with this id, or None when it does not exist (anymore).

        :param item_id: MA library track id as returned by AudioMuse-AI.
        """


@dataclass(slots=True)
class SeedRef:
    """The seed track as the service needs it (filled by the MA adapter)."""

    title: str
    artists: list[str] = field(default_factory=list)
    library_id: str | None = None


@dataclass(slots=True)
class SimilarOptions:
    """Per-request options, taken from the provider config."""

    eliminate_duplicates: bool | None = None
    mood_similarity: bool | None = None
    title_artist_fallback: bool = True


@dataclass(slots=True)
class SimilarStats:
    """Counters of the last request, for logging and diagnostics."""

    seed_by_id: bool = False
    used_title_artist: bool = False
    requested: int = 0
    received: int = 0
    unresolved: int = 0
    returned: int = 0


class SimilarTracksService(Generic[T]):
    """Answers "similar tracks" requests with AudioMuse-AI results as MA library tracks."""

    def __init__(
        self,
        client: AudioMuseClient,
        library: LibraryPort[T],
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize the service.

        :param client: AudioMuse-AI client.
        :param library: MA library adapter.
        :param logger: Logger to use.
        """
        self._client = client
        self._library = library
        self._logger = logger or logging.getLogger(__name__)
        self.last_stats = SimilarStats()

    async def similar_tracks(
        self, seed: SeedRef, limit: int, options: SimilarOptions | None = None
    ) -> list[T]:
        """
        Return up to ``limit`` MA library tracks that AudioMuse-AI considers similar.

        The seed is looked up by its library id; when AudioMuse-AI does not know that id
        (not analyzed yet, or a streaming track that is not in the library) and the fallback
        is enabled, AudioMuse-AI is asked by artist and title instead. Returns an empty
        list when AudioMuse-AI has no answer; connection and authentication errors propagate.

        :param seed: The seed track.
        :param limit: Maximum number of tracks to return.
        :param options: Request options.
        """
        opts = options or SimilarOptions()
        stats = SimilarStats()
        self.last_stats = stats
        if limit <= 0:
            return []
        n = min(MAX_REQUEST_N, limit * OVERFETCH_FACTOR + 1)
        stats.requested = n
        rows = None
        if seed.library_id:
            try:
                rows = await self._client.similar_tracks(
                    item_id=seed.library_id,
                    n=n,
                    eliminate_duplicates=opts.eliminate_duplicates,
                    mood_similarity=opts.mood_similarity,
                )
                stats.seed_by_id = True
            except AudioMuseNotFoundError:
                self._logger.debug("AudioMuse-AI does not know library track %s", seed.library_id)
        if rows is None and opts.title_artist_fallback and seed.title and seed.artists:
            stats.used_title_artist = True
            try:
                rows = await self._client.similar_tracks(
                    title=seed.title,
                    artist=seed.artists[0],
                    n=n,
                    eliminate_duplicates=opts.eliminate_duplicates,
                    mood_similarity=opts.mood_similarity,
                )
            except AudioMuseNotFoundError:
                self._logger.debug("AudioMuse-AI does not know %s", seed.title)
        if not rows:
            return []
        stats.received = len(rows)
        ids: list[str] = []
        seen = {seed.library_id} if seed.library_id else set()
        for row in rows:
            if row.item_id not in seen:
                seen.add(row.item_id)
                ids.append(row.item_id)
        result: list[T] = []
        for track in await self._load_all(ids):
            if track is None:
                stats.unresolved += 1
                continue
            result.append(track)
            if len(result) >= limit:
                break
        stats.returned = len(result)
        self._logger.debug(
            "Similar tracks for %s: by_id=%s fallback=%s received=%d unresolved=%d returned=%d",
            seed.title,
            stats.seed_by_id,
            stats.used_title_artist,
            stats.received,
            stats.unresolved,
            stats.returned,
        )
        return result

    async def _load_all(self, ids: list[str]) -> list[T | None]:
        semaphore = asyncio.Semaphore(RESOLVE_CONCURRENCY)

        async def _load(item_id: str) -> T | None:
            async with semaphore:
                return await self._library.get_track(item_id)

        return list(await asyncio.gather(*(_load(item_id) for item_id in ids)))
