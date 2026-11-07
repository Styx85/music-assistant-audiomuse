"""Fake AudioMuse-AI HTTP server for the tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

TOKEN = "test-token"

SIMILAR_ROWS = [
    {"item_id": "12", "title": "Song B", "author": "Band", "album": "LP", "distance": 0.1},
    {"item_id": "13", "title": "Song C", "author": "Other", "album": "unknown", "distance": 0.2},
    {"title": "broken row without id"},
]


@dataclass
class FakeState:
    """Requests seen by the fake servers and switches for error cases."""

    requests: list[tuple[str, dict[str, str], dict[str, str]]] = field(default_factory=list)
    similar_status: int = 200


def _auth_ok(request: web.Request) -> bool:
    return request.headers.get("Authorization") == f"Bearer {TOKEN}"


def build_audiomuse_app(state: FakeState) -> web.Application:
    """Return an aiohttp app that mimics the AudioMuse-AI endpoints used by the client."""

    async def record(request: web.Request) -> None:
        state.requests.append((request.path, dict(request.query), dict(request.headers)))

    async def health(request: web.Request) -> web.Response:
        await record(request)
        return web.json_response({"status": "ok"})

    async def version(request: web.Request) -> web.Response:
        await record(request)
        if not _auth_ok(request):
            # a careless proxy might echo the header back; the client must not pass it on
            echoed = request.headers.get("Authorization", "")
            return web.json_response(
                {"error_code": "AUTH_REQUIRED", "error_message": f"Bad credentials {echoed}"},
                status=401,
            )
        return web.json_response({"app_version": "1.2.3"})

    async def similar(request: web.Request) -> web.Response:
        await record(request)
        if not _auth_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        if state.similar_status != 200:
            return web.json_response(
                {"error_code": "NOT_FOUND", "error_message": "Target track not found."},
                status=state.similar_status,
            )
        return web.json_response(SIMILAR_ROWS)

    async def find_path(request: web.Request) -> web.Response:
        await record(request)
        return web.json_response({"path": SIMILAR_ROWS[:2], "total_distance": 0.3})

    async def clap(request: web.Request) -> web.Response:
        await record(request)
        body = await request.json()
        rows = SIMILAR_ROWS[: int(body.get("limit", 2))]
        return web.json_response({"query": body["query"], "results": rows, "count": len(rows)})

    async def not_json(request: web.Request) -> web.Response:
        await record(request)
        return web.Response(text="<html>proxy error</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/version", version)
    app.router.add_get("/api/similar_tracks", similar)
    app.router.add_get("/api/find_path", find_path)
    app.router.add_post("/api/clap/search", clap)
    app.router.add_get("/api/not_json", not_json)
    return app


@asynccontextmanager
async def serve(app: web.Application) -> AsyncIterator[tuple[str, aiohttp.ClientSession]]:
    """Start ``app`` on a free local port and yield its base URL plus a client session."""
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            yield str(server.make_url("")).rstrip("/"), session
    finally:
        await server.close()
