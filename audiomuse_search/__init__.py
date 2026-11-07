"""
Free-text search companion of the AudioMuse-AI provider.

Music Assistant only offers plugin providers (not metadata providers) to its global
search, so the text search lives in this small plugin. It has no settings and no
connection of its own: it uses the AudioMuse-AI metadata provider (domain ``audiomuse``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from music_assistant_models.enums import MediaType, ProviderFeature
from music_assistant_models.media_items import SearchResults

from music_assistant.models.plugin import PluginProvider
from music_assistant.providers.audiomuse.translations import register_translations

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

MAIN_DOMAIN = "audiomuse"
SUPPORTED_FEATURES = {ProviderFeature.SEARCH}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider instance with given configuration."""
    await register_translations(
        mass, Path(__file__).parent, manifest.domain, logging.getLogger(__name__)
    )
    return AudioMuseSearchPlugin(mass, manifest, config, set(SUPPORTED_FEATURES))


class AudioMuseSearchPlugin(PluginProvider):
    """Adds AudioMuse-AI's text-to-sound search to Music Assistant's search."""

    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 5,
    ) -> SearchResults:
        """
        Return library tracks whose sound matches the query.

        :param search_query: Free text describing the sound.
        :param media_types: Requested media types; only tracks are returned.
        :param limit: Maximum number of tracks.
        """
        if MediaType.TRACK not in media_types:
            return SearchResults()
        main = self.mass.get_provider(MAIN_DOMAIN)
        if main is None or not main.available or not hasattr(main, "text_search_tracks"):
            return SearchResults()
        return SearchResults(tracks=await main.text_search_tracks(search_query, limit))
