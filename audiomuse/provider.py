"""AudioMusePlugin - the Music Assistant provider class."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType, MediaType, ProviderFeature
from music_assistant_models.errors import (
    LoginFailed,
    MusicAssistantError,
    ProviderUnavailableError,
    SetupFailedError,
)
from music_assistant_models.media_items import RecommendationFolder, UniqueList

from music_assistant.models.metadata_provider import MetadataProvider

from .client import AudioMuseAuthError, AudioMuseClient, AudioMuseError
from .constants import (
    CONF_API_TOKEN,
    CONF_ELIMINATE_DUPLICATES,
    CONF_ENABLE_DISCOVER_ROW,
    CONF_LABEL_STATUS,
    CONF_MOOD_SIMILARITY,
    CONF_PREFER_OVER_BUILTIN,
    CONF_SERVER_NAME,
    CONF_TITLE_ARTIST_FALLBACK,
    CONF_URL,
    CONF_VERIFY_SSL,
    DISCOVER_CACHE_SECONDS,
    DISCOVER_ITEM_LIMIT,
    DISCOVER_PER_SEED,
    DISCOVER_ROW_ID,
    DISCOVER_SEED_COUNT,
    PRIORITY_DEFAULT,
    PRIORITY_PREFERRED,
    STATUS_REFRESH_SECONDS,
    TRISTATE_OFF,
    TRISTATE_ON,
    TRISTATE_SERVER_DEFAULT,
)
from .library import MassLibraryPort, track_to_seed
from .similar import SimilarOptions, SimilarTracksService
from .status import format_status

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.media_items import BrowseFolder, ItemMapping, MediaItemType, Track
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant

    from .similar import SeedRef

SUPPORTED_FEATURES = {ProviderFeature.SIMILAR_TRACKS, ProviderFeature.RECOMMENDATIONS}


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
        return (
            ConfigEntry(
                key=CONF_PREFER_OVER_BUILTIN,
                type=ConfigEntryType.BOOLEAN,
                default_value=True,
                required=False,
            ),
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
        try:
            return await self._service.similar_tracks(
                track_to_seed(track), limit, self._similar_options()
            )
        except AudioMuseError as err:
            raise ProviderUnavailableError(f"AudioMuse-AI: {err}") from err

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
