"""Constants for the AudioMuse-AI plugin provider."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "audiomuse"

# connection to AudioMuse-AI
CONF_URL: Final = "url"
CONF_API_TOKEN: Final = "api_token"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_SERVER_NAME: Final = "server_name"

# similar tracks behaviour
CONF_ELIMINATE_DUPLICATES: Final = "eliminate_duplicates"
CONF_MOOD_SIMILARITY: Final = "mood_similarity"
CONF_TITLE_ARTIST_FALLBACK: Final = "title_artist_fallback"
CONF_PREFER_OVER_BUILTIN: Final = "prefer_over_builtin"

# tri-state choices for options AudioMuse-AI can decide itself
TRISTATE_SERVER_DEFAULT: Final = "server_default"
TRISTATE_ON: Final = "on"
TRISTATE_OFF: Final = "off"

# Ask AudioMuse-AI for more candidates than MA wants: some ids may no longer exist in the
# MA library (removed since the last AudioMuse-AI analysis) and the seed itself is dropped.
OVERFETCH_FACTOR: Final = 2
MAX_REQUEST_N: Final = 200

# MA sorts plugin providers that support SIMILAR_TRACKS by this attribute (lower wins);
# providers without the attribute count as 50 (see MusicAssistant.get_providers_supporting_feature).
PRIORITY_PREFERRED: Final = 40
PRIORITY_DEFAULT: Final = 60

REQUEST_TIMEOUT_SECONDS: Final = 30
RESOLVE_CONCURRENCY: Final = 8
