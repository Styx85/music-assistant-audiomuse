"""AudioMusePlugin - the Music Assistant provider class."""

from __future__ import annotations

from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import LoginFailed, ProviderUnavailableError, SetupFailedError

from music_assistant.models.plugin import PluginProvider

from .client import AudioMuseAuthError, AudioMuseClient, AudioMuseError
from .constants import (
    CONF_API_TOKEN,
    CONF_ELIMINATE_DUPLICATES,
    CONF_MOOD_SIMILARITY,
    CONF_PREFER_OVER_BUILTIN,
    CONF_SERVER_NAME,
    CONF_TITLE_ARTIST_FALLBACK,
    CONF_URL,
    CONF_VERIFY_SSL,
    PRIORITY_DEFAULT,
    PRIORITY_PREFERRED,
    TRISTATE_OFF,
    TRISTATE_ON,
    TRISTATE_SERVER_DEFAULT,
)
from .library import MassLibraryPort, track_to_seed
from .similar import SimilarOptions, SimilarTracksService

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.media_items import Track
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant

SUPPORTED_FEATURES = {ProviderFeature.SIMILAR_TRACKS}


class AudioMusePlugin(PluginProvider):
    """Similar tracks (later also paths, text search, recommendations) from AudioMuse-AI."""

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
        # read by MusicAssistant.get_providers_supporting_feature (lower wins)
        self.priority = (
            PRIORITY_PREFERRED
            if bool(self.config.get_value(CONF_PREFER_OVER_BUILTIN))
            else PRIORITY_DEFAULT
        )

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
        self.logger.info("Connected to AudioMuse-AI %s", version or "(unknown version)")
        self._service = SimilarTracksService(
            self._client, MassLibraryPort(self.mass, self.logger), self.logger
        )

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
