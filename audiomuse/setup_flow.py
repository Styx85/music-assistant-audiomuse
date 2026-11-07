"""Setup flow for the AudioMuse-AI plugin: collect the connection and create the provider."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

from music_assistant.models.setup_flow import SetupFlowError

from .constants import CONF_API_TOKEN, CONF_SERVER_NAME, CONF_URL, CONF_VERIFY_SSL

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType

    from music_assistant.models.setup_flow import SetupSession

CONF_CLEAR_API_TOKEN = "clear_api_token"

_ENTRIES = (
    ConfigEntry(key=CONF_URL, type=ConfigEntryType.STRING, required=True),
    ConfigEntry(key=CONF_API_TOKEN, type=ConfigEntryType.SECURE_STRING, required=False),
    ConfigEntry(key=CONF_SERVER_NAME, type=ConfigEntryType.STRING, required=False, advanced=True),
    ConfigEntry(
        key=CONF_VERIFY_SSL,
        type=ConfigEntryType.BOOLEAN,
        default_value=True,
        required=False,
        advanced=True,
    ),
)


async def run_setup(session: SetupSession) -> None:
    """Ask for URL and token; loop back to the form while the provider does not load."""
    errors: dict[str, str] | None = None
    setup_data = dict(session.context.setup_data)
    while True:
        submitted = await session.form(
            _entries(setup_data), step_id="user", errors=errors, last_step=True
        )
        if submitted.pop(CONF_CLEAR_API_TOKEN, False):
            setup_data[CONF_API_TOKEN] = ""
            submitted.pop(CONF_API_TOKEN, None)
        elif not submitted.get(CONF_API_TOKEN):
            # the stored token is never sent to the client, so an empty field on a
            # reconfigure or retry means "keep the current one"; clearing it is explicit
            submitted.pop(CONF_API_TOKEN, None)
        setup_data.update(submitted)
        try:
            await session.finish(setup_data)
            return
        except SetupFlowError as err:
            errors = {"base": err.translation_key or str(err)}


def _entries(setup_data: dict[str, ConfigValueType]) -> list[ConfigEntry]:
    entries = [
        replace(entry, value=setup_data.get(entry.key, entry.value))
        for entry in _ENTRIES
        if entry.type != ConfigEntryType.SECURE_STRING
    ]
    entries.insert(1, _ENTRIES[1])
    if setup_data.get(CONF_API_TOKEN):
        entries.append(
            ConfigEntry(
                key=CONF_CLEAR_API_TOKEN,
                type=ConfigEntryType.BOOLEAN,
                required=False,
                default_value=False,
            )
        )
    return entries
