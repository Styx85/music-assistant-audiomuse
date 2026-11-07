"""AudioMusePlugin - the Music Assistant provider class."""

from __future__ import annotations

import asyncio
import contextvars
import time
from typing import TYPE_CHECKING

from aiohttp import ClientError

from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType, MediaType, ProviderFeature, ProviderType
from music_assistant_models.errors import (
    LoginFailed,
    MusicAssistantError,
    ProviderUnavailableError,
    SetupFailedError,
)
from music_assistant_models.media_items import RecommendationFolder, UniqueList

from music_assistant.models.metadata_provider import MetadataProvider
from music_assistant.models.music_provider import MusicProvider

from .client import AudioMuseAuthError, AudioMuseClient, AudioMuseError
from .constants import (
    CONF_API_TOKEN,
    CONF_ELIMINATE_DUPLICATES,
    CONF_ENABLE_DISCOVER_ROW,
    CONF_LABEL_STATUS,
    CONF_MOOD_SIMILARITY,
    CONF_PREFER_OVER_BUILTIN,
    CONF_FALLBACKS,
    CONF_SERVER_NAME,
    CONF_TITLE_ARTIST_FALLBACK,
    CONF_URL,
    CONF_VERIFY_SSL,
    DISCOVER_CACHE_SECONDS,
    DISCOVER_ITEM_LIMIT,
    DISCOVER_PER_SEED,
    DISCOVER_ROW_ID,
    DEFAULT_FALLBACKS,
    DISCOVER_SEED_COUNT,
    FALLBACK_NONE,
    PRIORITY_DEFAULT,
    PRIORITY_PREFERRED,
    STATUS_REFRESH_SECONDS,
    TRISTATE_OFF,
    TRISTATE_ON,
    TRISTATE_SERVER_DEFAULT,
)
from .library import MassLibraryPort, track_to_seed
from .similar import SimilarOptions, SimilarTracksService, with_fallbacks
from .status import format_status

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.media_items import BrowseFolder, ItemMapping, MediaItemType, Track
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant

    from .similar import SeedRef

SUPPORTED_FEATURES = {ProviderFeature.SIMILAR_TRACKS, ProviderFeature.RECOMMENDATIONS}
# the former on/off switch; only read to keep "no fallback" for installs that had turned it off
LEGACY_CONF_SONIC_FALLBACK = "sonic_fallback"
# set while this provider asks its fallbacks, so a fallback that loops back here returns nothing
_IN_FALLBACK: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "audiomuse_in_fallback", default=False
)


class AudioMusePlugin(MetadataProvider):
    """
    Similar tracks (later also paths, text search, recommendations) from AudioMuse-AI.

    A metadata provider rather than a plugin: Music Assistant asks metadata providers for
    similar tracks before plugin providers, sorted by ``priority``, so this is the only way
    to be asked before Last.fm (metadata, priority 50) and Sonic Similarity (plugin).
    """

    def __init__(
        self,
        mass: MusicAssistant,
        manifest: ProviderManifest,
        config: ProviderConfig,
        supported_features: set[ProviderFeature] | None = None,
    ) -> None:
        """Initialize the provider."""
        super().__init__(mass, manifest, config, supported_features or SUPPORTED_FEATURES)
        self._client: AudioMuseClient
        self._service: SimilarTracksService[Track]
        self._version: str | None = None
        self._status_text = format_status(None, None, None)
        self._status_task: asyncio.Task[None] | None = None
        # keyed by the seed ids: recently played is per user, so users never share entries
        self._discover_cache: dict[tuple[str, ...], tuple[float, list[Track]]] = {}

    @property
    def priority(self) -> int:
        """Return the provider priority (lower = asked first, Last.fm uses 50)."""
        if bool(self.config.get_value(CONF_PREFER_OVER_BUILTIN)):
            return PRIORITY_PREFERRED
        return PRIORITY_DEFAULT

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """
        Return the options of this provider instance (labels live in strings.json).

        URL, token, server name and SSL check are collected by the setup flow.
        """
        tristate = [
            ConfigValueOption(TRISTATE_SERVER_DEFAULT),
            ConfigValueOption(TRISTATE_ON),
            ConfigValueOption(TRISTATE_OFF),
        ]
        fallback_options = self._fallback_options()
        fallback_entries = tuple(
            ConfigEntry(
                key=key,
                type=ConfigEntryType.STRING,
                options=fallback_options,
                default_value=default,
                required=False,
                category="fallback",
            )
            for key, default in zip(CONF_FALLBACKS, DEFAULT_FALLBACKS, strict=True)
        )
        return (
            ConfigEntry(
                key=CONF_PREFER_OVER_BUILTIN,
                type=ConfigEntryType.BOOLEAN,
                default_value=True,
                required=False,
            ),
            *fallback_entries,
            ConfigEntry(
                key=CONF_ELIMINATE_DUPLICATES,
                type=ConfigEntryType.STRING,
                options=tristate,
                default_value=TRISTATE_SERVER_DEFAULT,
                required=False,
                advanced=True,
            ),
            ConfigEntry(
                key=CONF_MOOD_SIMILARITY,
                type=ConfigEntryType.STRING,
                options=tristate,
                default_value=TRISTATE_SERVER_DEFAULT,
                required=False,
                advanced=True,
            ),
            ConfigEntry(
                key=CONF_TITLE_ARTIST_FALLBACK,
                type=ConfigEntryType.BOOLEAN,
                default_value=True,
                required=False,
                advanced=True,
            ),
            ConfigEntry(
                key=CONF_ENABLE_DISCOVER_ROW,
                type=ConfigEntryType.BOOLEAN,
                default_value=True,
                required=False,
                category="discover",
            ),
            ConfigEntry(
                key=CONF_LABEL_STATUS,
                type=ConfigEntryType.LABEL,
                label=self._status_text,
                required=False,
                category="status",
            ),
        )

    async def handle_async_init(self) -> None:
        """Create the client and check that AudioMuse-AI answers."""
        url = str(self.get_setup_value(CONF_URL) or "").strip()
        if not url:
            raise SetupFailedError("AudioMuse-AI URL is required")
        session = (
            self.mass.http_session
            if self.get_setup_value(CONF_VERIFY_SSL, True) is not False
            else self.mass.http_session_no_ssl
        )
        token = self.get_setup_value(CONF_API_TOKEN)
        self._client = AudioMuseClient(
            session,
            url,
            api_token=str(token) if token else None,
            server=str(self.get_setup_value(CONF_SERVER_NAME) or "") or None,
        )
        try:
            version = await self._client.version()
        except AudioMuseAuthError as err:
            raise LoginFailed(f"AudioMuse-AI rejected the API token: {err}") from err
        except AudioMuseError as err:
            raise SetupFailedError(f"AudioMuse-AI is not reachable: {err}") from err
        self._version = version
        self.logger.info("Connected to AudioMuse-AI %s", version or "(unknown version)")
        self._service = SimilarTracksService(
            self._client, MassLibraryPort(self.mass, self.logger), self.logger
        )

    async def loaded_in_mass(self) -> None:
        """Start the background status refresh."""
        await super().loaded_in_mass()
        self._status_task = self.mass.create_task(self._status_loop())

    async def unload(self, is_removed: bool = False) -> None:
        """Stop the background status refresh."""
        if self._status_task and not self._status_task.done():
            self._status_task.cancel()
        await super().unload(is_removed)

    async def get_similar_tracks(self, track: Track, limit: int = 25) -> list[Track]:
        """
        Return MA library tracks that AudioMuse-AI considers similar.

        :param track: The reference track (full library item, handed over by MA).
        :param limit: Maximum number of tracks.
        """
        if _IN_FALLBACK.get():
            return []
        fallbacks = [
            (instance_id, self._fallback_asker(instance_id, track, limit))
            for instance_id in self._fallback_chain()
        ]
        try:
            tracks, source, primary_error = await with_fallbacks(
                lambda: self._service.similar_tracks(
                    track_to_seed(track), limit, self._similar_options()
                ),
                fallbacks,
            )
        except AudioMuseError as err:
            raise ProviderUnavailableError(f"AudioMuse-AI: {err}") from err
        if source != "audiomuse":
            self.logger.debug(
                "Similar tracks for %s served by %s (AudioMuse-AI: %s)",
                track.name,
                source,
                primary_error or "no result",
            )
        return tracks

    async def get_recommendations(self) -> list[RecommendationFolder]:
        """Return the discover row descriptor (no items, no backend call)."""
        if not bool(self.config.get_value(CONF_ENABLE_DISCOVER_ROW)):
            return []
        return [self._discover_folder()]

    async def get_recommendation_items(
        self, item_id: str
    ) -> UniqueList[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Return the tracks of the discover row: similar to the recently played tracks.

        :param item_id: The row id, as returned by get_recommendations.
        """
        if item_id != DISCOVER_ROW_ID or not bool(self.config.get_value(CONF_ENABLE_DISCOVER_ROW)):
            return UniqueList()
        seeds = await self._recent_seeds()
        key = tuple(s.library_id or "" for s in seeds)
        now = time.monotonic()
        cached = self._discover_cache.get(key)
        if cached and now - cached[0] < DISCOVER_CACHE_SECONDS:
            return UniqueList(cached[1])
        try:
            tracks = await self._service.inspired_by(
                seeds, DISCOVER_ITEM_LIMIT, DISCOVER_PER_SEED, self._similar_options()
            )
        except AudioMuseError as err:
            self.logger.debug("Discover row unavailable: %s", err)
            return UniqueList()
        self._discover_cache = {
            k: v for k, v in self._discover_cache.items() if now - v[0] < DISCOVER_CACHE_SECONDS
        }
        self._discover_cache[key] = (now, tracks)
        return UniqueList(tracks)

    async def text_search_tracks(self, query: str, limit: int) -> list[Track]:
        """
        Return library tracks matching a free-text description (used by audiomuse_search).

        Failures raise ProviderUnavailableError, so Music Assistant does not cache them.

        :param query: Free text, e.g. "calm piano in the evening".
        :param limit: Maximum number of tracks.
        """
        try:
            return await self._service.text_search(query, limit)
        except AudioMuseError as err:
            raise ProviderUnavailableError(f"AudioMuse-AI text search: {err}") from err

    def _fallback_chain(self) -> list[str]:
        """Return the configured fallback provider instance ids, in order, without repeats."""
        raw = self.mass.config.get_raw_provider_config_value
        if raw(self.instance_id, CONF_FALLBACKS[0]) is None and (
            raw(self.instance_id, LEGACY_CONF_SONIC_FALLBACK) is False
        ):
            return []
        chain: list[str] = []
        for key, default in zip(CONF_FALLBACKS, DEFAULT_FALLBACKS, strict=True):
            value = str(self.config.get_value(key) or default)
            if value != FALLBACK_NONE and value != self.instance_id and value not in chain:
                chain.append(value)
        return chain

    def _fallback_options(self) -> list[ConfigValueOption]:
        """Offer every loaded provider that can deliver similar tracks, plus the stored values."""
        options = [ConfigValueOption(FALLBACK_NONE)]
        seen = {FALLBACK_NONE, self.instance_id}
        candidates = self.mass.get_providers_supporting_feature(
            ProviderFeature.SIMILAR_TRACKS,
            priority=(ProviderType.MUSIC, ProviderType.METADATA, ProviderType.PLUGIN),
        )
        for prov in candidates:
            if prov.instance_id not in seen:
                seen.add(prov.instance_id)
                options.append(ConfigValueOption(prov.instance_id, title=prov.name))
        # keep stored choices selectable even while their provider is not loaded (yet)
        for key, default in zip(CONF_FALLBACKS, DEFAULT_FALLBACKS, strict=True):
            value = str(self.config.get_value(key) or default)
            if value not in seen:
                seen.add(value)
                options.append(ConfigValueOption(value, title=value))
        return options

    def _fallback_asker(
        self, instance_id: str, track: Track, limit: int
    ) -> Callable[[], Awaitable[list[Track]]]:
        async def _ask() -> list[Track]:
            token = _IN_FALLBACK.set(True)
            try:
                return await self._similar_from_provider(instance_id, track, limit)
            finally:
                _IN_FALLBACK.reset(token)

        return _ask

    async def _similar_from_provider(
        self, instance_id: str, track: Track, limit: int
    ) -> list[Track]:
        """Ask another provider for similar tracks; empty when it is missing or fails."""
        prov = self.mass.get_provider(instance_id)
        if (
            prov is None
            or not prov.available
            or ProviderFeature.SIMILAR_TRACKS not in prov.supported_features
        ):
            return []
        try:
            if isinstance(prov, MusicProvider):
                # music providers want their own track id: only usable when the track has one
                mapping = next(
                    (m for m in track.provider_mappings if m.provider_instance == instance_id),
                    None,
                )
                if mapping is None:
                    return []
                return list(await prov.get_similar_tracks(mapping.item_id, limit=limit))
            return list(await prov.get_similar_tracks(track, limit=limit))
        except (
            MusicAssistantError,
            ClientError,
            OSError,
            TimeoutError,
            NotImplementedError,
        ) as err:
            self.logger.debug("Fallback %s failed for %s: %s", instance_id, track.name, err)
            return []

    def _discover_folder(self) -> RecommendationFolder:
        return RecommendationFolder(
            item_id=DISCOVER_ROW_ID,
            provider=self.instance_id,
            name="Inspired by recently played",
            translation_key="inspired_by_recently_played",
            subtitle="AudioMuse-AI",
            icon="mdi-waveform",
        )

    async def _recent_seeds(self) -> list[SeedRef]:
        try:
            recent = await self.mass.music.recently_played(
                limit=DISCOVER_SEED_COUNT, media_types=[MediaType.TRACK], fully_played_only=False
            )
        except MusicAssistantError as err:
            self.logger.debug("recently_played failed: %s", err)
            return []
        seeds: list[SeedRef] = []
        for mapping in recent:
            try:
                track = await self.mass.music.tracks.get(
                    mapping.item_id, mapping.provider, allow_update_metadata=False
                )
            except MusicAssistantError:
                continue
            seeds.append(track_to_seed(track))
        return seeds

    async def _status_loop(self) -> None:
        while True:
            await self._refresh_status()
            await asyncio.sleep(STATUS_REFRESH_SECONDS)

    async def _refresh_status(self) -> None:
        try:
            summary = await self._client.dashboard_summary()
            active = await self._client.active_task()
        except AudioMuseError as err:
            self._status_text = format_status(self._version, None, None, str(err))
            return
        self._status_text = format_status(self._version, summary, active)

    def _similar_options(self) -> SimilarOptions:
        return SimilarOptions(
            eliminate_duplicates=_tristate(self.config.get_value(CONF_ELIMINATE_DUPLICATES)),
            mood_similarity=_tristate(self.config.get_value(CONF_MOOD_SIMILARITY)),
            title_artist_fallback=bool(self.config.get_value(CONF_TITLE_ARTIST_FALLBACK)),
        )


def _tristate(value: object) -> bool | None:
    if value == TRISTATE_ON:
        return True
    if value == TRISTATE_OFF:
        return False
    return None
