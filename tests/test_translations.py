"""Tests for the runtime translation registration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

from audiomuse.translations import flatten, load_strings, register_translations

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "audiomuse"
SEARCH_DIR = Path(__file__).resolve().parent.parent / "audiomuse_search"


def _keys(path: Path) -> set[str]:
    return set(flatten(json.loads(path.read_text(encoding="utf-8")), ""))


def test_flatten_matches_music_assistant_key_format() -> None:
    data = {"config_entries": {"x": {"label": "X", "options": {"on": "On"}}}, "n": 1}
    assert flatten(data, "provider.audiomuse.") == {
        "provider.audiomuse.config_entries.x.label": "X",
        "provider.audiomuse.config_entries.x.options.on": "On",
    }


def test_every_language_has_the_same_keys_as_english() -> None:
    for package in (PACKAGE_DIR, SEARCH_DIR):
        english = _keys(package / "strings.json")
        for path in (package / "translations").glob("*.json"):
            assert _keys(path) == english, path


def test_load_strings() -> None:
    strings = load_strings(PACKAGE_DIR, "audiomuse")
    assert strings["en"]["provider.audiomuse.config_entries.prefer_over_builtin.label"]
    assert strings["de"]["provider.audiomuse.config_entries.prefer_over_builtin.label"] == (
        "AudioMuse-AI zuerst fragen"
    )


class FakeController:
    def __init__(self) -> None:
        self._source = {"common.x": "X"}
        self._locales: dict[str, dict[str, str]] = {}
        self.loaded: list[str] = []

    async def ensure_locale_loaded(self, locale: str) -> None:
        self.loaded.append(locale)
        self._locales.setdefault(locale, {"common.x": "X (de)"})


def test_register_merges_after_loading_the_full_bundle(run) -> None:
    controller = FakeController()
    mass = SimpleNamespace(translations=controller)
    assert run(register_translations(mass, PACKAGE_DIR, "audiomuse", logging.getLogger("t")))
    key = "provider.audiomuse.config_entries.prefer_over_builtin.label"
    assert controller._source[key] == "Ask AudioMuse-AI first"
    assert controller._locales["de"][key] == "AudioMuse-AI zuerst fragen"
    assert controller._locales["de"]["common.x"] == "X (de)"  # MA's own strings kept
    assert controller.loaded == ["de"]


def test_register_skips_unknown_controller_layout(run) -> None:
    mass = SimpleNamespace(translations=SimpleNamespace())
    assert not run(register_translations(mass, PACKAGE_DIR, "audiomuse", logging.getLogger("t")))


def test_broken_language_file_does_not_affect_others(tmp_path: Path) -> None:
    (tmp_path / "strings.json").write_text('{"manifest": {"description": "EN"}}')
    (tmp_path / "translations").mkdir()
    (tmp_path / "translations" / "de.json").write_text("[]")
    (tmp_path / "translations" / "fr.json").write_text("{broken")
    (tmp_path / "translations" / "nl.json").write_text('{"manifest": {"description": "NL"}}')
    strings = load_strings(tmp_path, "x", logging.getLogger("t"))
    assert strings == {
        "en": {"provider.x.manifest.description": "EN"},
        "nl": {"provider.x.manifest.description": "NL"},
    }
