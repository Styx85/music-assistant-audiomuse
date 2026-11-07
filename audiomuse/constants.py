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
CONF_RADIUS_SIMILARITY: Final = "radius_similarity"
CONF_TITLE_ARTIST_FALLBACK: Final = "title_artist_fallback"
CONF_PREFER_OVER_BUILTIN: Final = "prefer_over_builtin"
# ranked fallback sources for similar tracks (provider instance ids, or FALLBACK_NONE)
CONF_FALLBACKS: Final = ("fallback_1", "fallback_2", "fallback_3")
FALLBACK_NONE: Final = "none"
DEFAULT_FALLBACKS: Final = ("sonic_similarity", FALLBACK_NONE, FALLBACK_NONE)

# discover page row and status
CONF_ENABLE_DISCOVER_ROW: Final = "enable_discover_row"
CONF_LABEL_STATUS: Final = "label_status"
DISCOVER_ROW_ID: Final = "audiomuse_inspired_by_recently_played"
DISCOVER_SEED_COUNT: Final = 5
DISCOVER_PER_SEED: Final = 10
DISCOVER_ITEM_LIMIT: Final = 12
DISCOVER_CACHE_SECONDS: Final = 300

# mood and alchemy rows on the discover page
CONF_ENABLE_MOOD_ROWS: Final = "enable_mood_rows"
CONF_ENABLE_ALCHEMY_ROWS: Final = "enable_alchemy_rows"
MOODS: Final = ("happy", "relaxed", "danceable", "party", "aggressive", "sad")
MOOD_ROW_PREFIX: Final = "audiomuse_mood_"
ANCHOR_ROW_PREFIX: Final = "audiomuse_anchor_"
ROW_ITEM_LIMIT: Final = 25
ROW_CACHE_SECONDS: Final = 600
STATUS_REFRESH_SECONDS: Final = 300

# tri-state choices for options AudioMuse-AI can decide itself
TRISTATE_SERVER_DEFAULT: Final = "server_default"
TRISTATE_ON: Final = "on"
TRISTATE_OFF: Final = "off"

# Ask AudioMuse-AI for more candidates than MA wants: some ids may no longer exist in the
# MA library (removed since the last AudioMuse-AI analysis) and the seed itself is dropped.
OVERFETCH_FACTOR: Final = 2
MAX_REQUEST_N: Final = 200

# Metadata providers are asked for similar tracks in this order (lower first); Last.fm and
# the other built-in metadata providers use 50 (see MetadataProvider.priority).
PRIORITY_PREFERRED: Final = 10
PRIORITY_DEFAULT: Final = 60

REQUEST_TIMEOUT_SECONDS: Final = 30
RESOLVE_CONCURRENCY: Final = 8
