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

from .client import AudioMuseClient, AudioMuseError, AudioMuseNotFoundError, SimilarTrack
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

    async def inspired_by(
        self,
        seeds: list[SeedRef],
        limit: int,
        per_seed: int,
        options: SimilarOptions | None = None,
        timeout: float = 20.0,
    ) -> list[T]:
        """
        Return tracks similar to several seeds (e.g. recently played), most recent seed first.

        All seeds are asked at once within ``timeout``; seeds AudioMuse-AI does not know or
        that do not answer in time are skipped, the seeds themselves are never returned.
        Raises the first AudioMuse error only when no seed produced any result.

        :param seeds: Seed tracks, most important first (only library seeds are used).
        :param limit: Maximum number of tracks to return.
        :param per_seed: Neighbours to request per seed.
        :param options: Request options.
        :param timeout: Time budget for all AudioMuse-AI requests together, in seconds.
        """
        opts = options or SimilarOptions()
        seed_ids = list(dict.fromkeys(s.library_id for s in seeds if s.library_id))
        if limit <= 0 or not seed_ids:
            return []
        errors: list[AudioMuseError] = []

        async def _ask(seed_id: str) -> list[SimilarTrack]:
            try:
                async with asyncio.timeout(timeout):
                    return await self._client.similar_tracks(
                        item_id=seed_id,
                        n=min(MAX_REQUEST_N, per_seed + 1),
                        eliminate_duplicates=opts.eliminate_duplicates,
                        mood_similarity=opts.mood_similarity,
                    )
            except (AudioMuseNotFoundError, TimeoutError):
                return []
            except AudioMuseError as err:
                errors.append(err)
                return []

        per_seed_rows = await asyncio.gather(*(_ask(seed_id) for seed_id in seed_ids))
        if errors and not any(per_seed_rows):
            raise errors[0]
        seen = set(seed_ids)
        ids: list[str] = []
        for rows in per_seed_rows:
            for row in rows:
                if row.item_id not in seen:
                    seen.add(row.item_id)
                    ids.append(row.item_id)
        ids = ids[: limit * OVERFETCH_FACTOR]
        tracks = [t for t in await self._load_all(ids) if t is not None]
        return tracks[:limit]

    async def text_search(self, query: str, limit: int) -> list[T]:
        """
        Return library tracks whose sound matches a free-text description (CLAP search).

        Errors (including "text index not built yet") propagate, so callers can avoid
        caching a failure as an empty result.

        :param query: Free text, e.g. "calm piano in the evening".
        :param limit: Maximum number of tracks.
        """
        query = query.strip()
        if not query or limit <= 0:
            return []
        try:
            rows = await self._client.text_search(query, limit=min(MAX_REQUEST_N, limit * 2))
        except AudioMuseNotFoundError:
            return []
        ids = list(dict.fromkeys(row.item_id for row in rows))
        tracks = [t for t in await self._load_all(ids) if t is not None]
        return tracks[:limit]

    async def _load_all(self, ids: list[str]) -> list[T | None]:
        semaphore = asyncio.Semaphore(RESOLVE_CONCURRENCY)

        async def _load(item_id: str) -> T | None:
            async with semaphore:
                return await self._library.get_track(item_id)

        return list(await asyncio.gather(*(_load(item_id) for item_id in ids)))
