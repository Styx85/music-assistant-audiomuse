"""
Test setup without a Music Assistant installation.

* The provider package is registered as ``audiomuse`` without executing its
  ``__init__.py`` (which imports Music Assistant), so its pure modules can be imported.
* A minimal stand-in for ``music_assistant_models.errors`` lets ``library.py`` be
  imported; it is only installed when the real package is missing.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "audiomuse"

if "audiomuse" not in sys.modules:
    package = types.ModuleType("audiomuse")
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules["audiomuse"] = package

if importlib.util.find_spec("music_assistant_models") is None:
    models = types.ModuleType("music_assistant_models")
    models.__path__ = []
    errors = types.ModuleType("music_assistant_models.errors")

    class MusicAssistantError(Exception):
        """Stand-in for the real base error."""

    errors.MusicAssistantError = MusicAssistantError
    sys.modules["music_assistant_models"] = models
    sys.modules["music_assistant_models.errors"] = errors


@pytest.fixture
def run() -> Callable[[Awaitable[Any]], Any]:
    """Run a coroutine to completion (no pytest-asyncio needed)."""

    def _run(coro: Awaitable[Any]) -> Any:
        return asyncio.run(coro)  # type: ignore[arg-type]

    return _run
