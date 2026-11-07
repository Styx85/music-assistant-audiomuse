"""
Runtime registration of this provider's strings with Music Assistant.

Music Assistant compiles every built-in provider's ``strings.json`` into its global
``translations/<lang>.json`` files at build time, so a provider mounted into the image
(not part of that build) shows raw keys. Until the provider is part of Music Assistant,
it merges its own strings into the translation controller when it is set up: English from
``strings.json`` and other languages from ``translations/<lang>.json`` (same nesting),
flattened exactly like ``scripts/build_translations.py`` does.

This touches the controller's internal dictionaries; if they change, registration is
skipped with a debug message and the UI falls back to the raw keys.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


def flatten(data: dict[str, Any], prefix: str) -> dict[str, str]:
    """
    Flatten a nested strings dict into dotted, prefixed keys with string leaves.

    :param data: Parsed ``strings.json`` content.
    :param prefix: Key prefix, e.g. ``provider.audiomuse.``.
    """
    out: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{full_key}."))
        elif isinstance(value, str):
            out[full_key] = value
    return out


def load_strings(package_dir: Path, domain: str) -> dict[str, dict[str, str]]:
    """
    Return ``{language: {fully-qualified key: text}}`` for a provider package.

    :param package_dir: The provider's folder (holding ``strings.json``).
    :param domain: The provider domain used in the key prefix.
    """
    prefix = f"provider.{domain}."
    result: dict[str, dict[str, str]] = {}
    source = package_dir / "strings.json"
    if source.is_file():
        result["en"] = flatten(json.loads(source.read_text(encoding="utf-8")), prefix)
    for path in sorted((package_dir / "translations").glob("*.json")):
        result[path.stem] = flatten(json.loads(path.read_text(encoding="utf-8")), prefix)
    return result


async def register_translations(
    mass: Any, package_dir: Path, domain: str, logger: logging.Logger
) -> bool:
    """
    Merge the provider's strings into Music Assistant's translation controller.

    :param mass: The Music Assistant instance.
    :param package_dir: The provider's folder.
    :param domain: The provider domain.
    :param logger: Logger for diagnostics.
    :return: True when the strings were registered.
    """
    controller = getattr(mass, "translations", None)
    source = getattr(controller, "_source", None)
    locales = getattr(controller, "_locales", None)
    if not isinstance(source, dict) or not isinstance(locales, dict):
        logger.debug("Translation controller layout unknown; provider texts stay untranslated")
        return False
    try:
        strings = load_strings(package_dir, domain)
    except (OSError, ValueError) as err:
        logger.warning("Could not read provider translations: %s", err)
        return False
    for language, texts in strings.items():
        if language == "en":
            source.update(texts)
            continue
        # load Music Assistant's own bundle first: a pre-filled entry would stop it from
        # ever loading the full language file
        await controller.ensure_locale_loaded(language)
        bundle = locales.setdefault(language, {})
        bundle.update(texts)
    return True
