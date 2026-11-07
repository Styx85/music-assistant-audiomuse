"""
AudioMuse-AI plugin provider for Music Assistant.

Uses a self-hosted AudioMuse-AI server (https://github.com/NeptuneHub/AudioMuse-AI) as a
source for "similar tracks", which powers Music Assistant's radio mode and autoplay.
AudioMuse-AI analyzes the Music Assistant library itself (its ``musicassistant`` server
type), so the track ids it returns are Music Assistant library ids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .provider import SUPPORTED_FEATURES, AudioMusePlugin

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider instance with given configuration."""
    return AudioMusePlugin(mass, manifest, config, set(SUPPORTED_FEATURES))
