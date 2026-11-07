"""Music Assistant side: seed extraction and loading library tracks by id."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from music_assistant_models.errors import MusicAssistantError

from .similar import SeedRef

if TYPE_CHECKING:
    from music_assistant_models.media_items import Track

    from music_assistant.mass import MusicAssistant

LIBRARY = "library"


def track_to_seed(track: Track) -> SeedRef:
    """
    Extract the seed from the track MA hands to ``get_similar_tracks``.

    :param track: The reference track (usually a library item).
    """
    return SeedRef(
        title=track.name,
        artists=[artist.name for artist in track.artists],
        library_id=str(track.item_id) if track.provider == LIBRARY else None,
    )


class MassLibraryPort:
    """Loads MA library tracks by the ids AudioMuse-AI returns."""

    def __init__(self, mass: MusicAssistant, logger: logging.Logger) -> None:
        """
        Initialize the adapter.

        :param mass: The Music Assistant instance.
        :param logger: Logger of the provider.
        """
        self._mass = mass
        self._logger = logger

    async def get_track(self, item_id: str) -> Track | None:
        """
        Return the library track, or None when the id is unknown (e.g. removed meanwhile).

        :param item_id: MA library track id.
        """
        if not item_id.isdigit():
            # not an MA library id: AudioMuse-AI is probably bound to another server type
            self._logger.debug("AudioMuse-AI result %s is not an MA library id", item_id)
            return None
        try:
            return await self._mass.music.tracks.get_library_item(item_id)
        except MusicAssistantError as err:
            self._logger.debug("AudioMuse-AI result %s is not in the library: %s", item_id, err)
            return None
