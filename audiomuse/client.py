"""
Minimal async client for the AudioMuse-AI HTTP API.

Only depends on aiohttp, so it can be tested without a Music Assistant installation.
Endpoints and payloads follow AudioMuse-AI as of November 2026 (app_ivf.py, app_path.py,
app_clap_search.py). All ids are the ids of the AudioMuse-AI default media server (or of
the server named in ``server``), never AudioMuse-AI's internal content ids. With the
``musicassistant`` server type these are Music Assistant library track ids.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aiohttp

from .constants import REQUEST_TIMEOUT_SECONDS


class AudioMuseError(Exception):
    """Base error for AudioMuse-AI requests."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None) -> None:
        """
        Initialize the error.

        :param message: Human readable message (never contains the API token).
        :param status: HTTP status code, if a response was received.
        :param code: AudioMuse-AI ``error_code`` from the response body, if any.
        """
        super().__init__(message)
        self.status = status
        self.code = code


class AudioMuseAuthError(AudioMuseError):
    """The API token was rejected (401/403)."""


class AudioMuseNotFoundError(AudioMuseError):
    """The seed track is unknown to AudioMuse-AI or has no neighbours (404)."""


class AudioMuseUnavailableError(AudioMuseError):
    """AudioMuse-AI is unreachable, timed out, or answered with a server error."""


@dataclass(frozen=True, slots=True)
class SimilarTrack:
    """One result row of ``/api/similar_tracks`` or ``/api/find_path``."""

    item_id: str
    title: str
    artist: str
    album: str | None
    album_artist: str | None
    distance: float | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> SimilarTrack:
        """
        Build a result from a raw JSON row.

        :param row: One element of the JSON array returned by AudioMuse-AI.
        """
        album = row.get("album")
        album_artist = row.get("album_artist")
        distance = row.get("distance")
        return cls(
            item_id=str(row["item_id"]),
            title=str(row.get("title") or ""),
            artist=str(row.get("author") or row.get("artist") or ""),
            album=None if album in (None, "", "unknown") else str(album),
            album_artist=None if album_artist in (None, "", "unknown") else str(album_artist),
            distance=float(distance) if isinstance(distance, int | float) else None,
        )


class AudioMuseClient:
    """Async client for the AudioMuse-AI REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_token: str | None = None,
        server: str | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """
        Initialize the client.

        :param session: Shared aiohttp session (owned by the caller).
        :param base_url: Base URL of AudioMuse-AI, e.g. ``http://audiomuse:8000``.
        :param api_token: AudioMuse-AI ``API_TOKEN``; sent as Bearer token when set.
        :param server: Optional AudioMuse-AI music server name; omitted means default server.
        :param timeout: Total timeout per request in seconds.
        """
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = api_token or None
        self._server = server or None
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def health(self) -> bool:
        """Return True when the unauthenticated liveness probe answers ``ok``."""
        data = await self._request("GET", "/api/health", authenticated=False)
        return isinstance(data, dict) and data.get("status") == "ok"

    async def version(self) -> str | None:
        """Return the AudioMuse-AI version; also proves that the API token is accepted."""
        data = await self._request("GET", "/api/version")
        if isinstance(data, dict) and data.get("app_version"):
            return str(data["app_version"])
        return None

    async def similar_tracks(
        self,
        *,
        item_id: str | None = None,
        title: str | None = None,
        artist: str | None = None,
        n: int = 25,
        eliminate_duplicates: bool | None = None,
        mood_similarity: bool | None = None,
    ) -> list[SimilarTrack]:
        """
        Return tracks that sound similar to a seed track.

        :param item_id: Media server item id of the seed (preferred).
        :param title: Seed title, only used together with ``artist`` when no item_id is given.
        :param artist: Seed artist, only used together with ``title``.
        :param n: Number of neighbours to request.
        :param eliminate_duplicates: Limit songs per artist; None keeps the server default.
        :param mood_similarity: Also filter by mood features; None keeps the server default.
        :raises AudioMuseNotFoundError: The seed is not analyzed or has no neighbours.
        """
        params: dict[str, str] = {"n": str(max(1, n))}
        if item_id:
            params["item_id"] = item_id
        elif title and artist:
            params["title"] = title
            params["artist"] = artist
        else:
            raise ValueError("either item_id or title and artist are required")
        if eliminate_duplicates is not None:
            params["eliminate_duplicates"] = _bool_param(eliminate_duplicates)
        if mood_similarity is not None:
            params["mood_similarity"] = _bool_param(mood_similarity)
        data = await self._request("GET", "/api/similar_tracks", params=params)
        return _parse_rows(data)

    async def find_path(
        self, start_item_id: str, end_item_id: str, max_steps: int | None = None
    ) -> list[SimilarTrack]:
        """
        Return a sequence of tracks that moves smoothly from one track to another.

        :param start_item_id: Media server item id of the first track.
        :param end_item_id: Media server item id of the last track.
        :param max_steps: Maximum number of intermediate songs; None uses the server default.
        :raises AudioMuseNotFoundError: No path could be built.
        """
        params = {"start_song_id": start_item_id, "end_song_id": end_item_id}
        if max_steps is not None:
            params["max_steps"] = str(max_steps)
        data = await self._request("GET", "/api/find_path", params=params)
        if not isinstance(data, dict):
            raise AudioMuseError("unexpected response from /api/find_path")
        return _parse_rows(data.get("path"))

    async def text_search(self, query: str, limit: int = 25) -> list[SimilarTrack]:
        """
        Return tracks whose CLAP audio embedding matches a free-text description.

        :param query: Free text, e.g. "calm piano in the evening".
        :param limit: Maximum number of tracks.
        """
        data = await self._request(
            "POST", "/api/clap/search", json_body={"query": query, "limit": limit}
        )
        if not isinstance(data, dict):
            raise AudioMuseError("unexpected response from /api/clap/search")
        return _parse_rows(data.get("results"))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """
        Perform a request and return the decoded JSON body.

        :param method: HTTP method.
        :param path: Path below the base URL.
        :param params: Query parameters.
        :param json_body: JSON request body.
        :param authenticated: Send the Bearer token (when configured).
        """
        headers = {"Accept": "application/json"}
        if authenticated and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        query = dict(params or {})
        if self._server and authenticated:
            query["server"] = self._server
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                params=query or None,
                json=json_body,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                body: Any
                try:
                    body = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
                if resp.status < 400:
                    if body is None:
                        raise AudioMuseError(f"{path}: response is not JSON", resp.status)
                    return body
                _raise_for_status(path, resp.status, body, self._token)
        except AudioMuseError:
            raise
        except TimeoutError as err:
            raise AudioMuseUnavailableError(f"{path}: timeout") from err
        except aiohttp.ClientError as err:
            raise AudioMuseUnavailableError(f"{path}: {type(err).__name__}") from err


def _raise_for_status(path: str, status: int, body: Any, token: str | None) -> None:
    """Translate an error response into the matching exception (never echoing the token)."""
    code = None
    message = f"{path}: HTTP {status}"
    if isinstance(body, dict):
        code = body.get("error_code")
        detail = body.get("error_message") or body.get("error") or body.get("message")
        if detail:
            message = f"{message}: {detail}"
    if token:
        message = message.replace(token, "***")
    message = message[:400]
    if status in (401, 403):
        raise AudioMuseAuthError(message, status, code)
    if status == 404:
        raise AudioMuseNotFoundError(message, status, code)
    if status >= 500 or status == 429:
        raise AudioMuseUnavailableError(message, status, code)
    raise AudioMuseError(message, status, code)


def _parse_rows(data: Any) -> list[SimilarTrack]:
    """Parse a JSON array of track rows, skipping malformed entries."""
    if not isinstance(data, list):
        raise AudioMuseError("expected a list of tracks")
    result: list[SimilarTrack] = []
    for row in data:
        if isinstance(row, dict) and row.get("item_id"):
            result.append(SimilarTrack.from_row(row))
    return result


def _bool_param(value: bool) -> str:
    return "true" if value else "false"


__all__ = [
    "AudioMuseAuthError",
    "AudioMuseClient",
    "AudioMuseError",
    "AudioMuseNotFoundError",
    "AudioMuseUnavailableError",
    "SimilarTrack",
]
