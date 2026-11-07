# AudioMuse-AI for Music Assistant

A [Music Assistant](https://music-assistant.io) provider that uses a self-hosted
[AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI) server for **similar tracks**.
That powers Music Assistant's *Similar tracks*, **radio mode** and **autoplay "similar"**
with AudioMuse-AI's sonic analysis (MusiCNN + CLAP), plus:

- a discover row **"Inspired by recently played"** (tracks similar to what you played last),
- **free-text search** by sound ("calm piano in the evening") via the companion
  `audiomuse_search` plugin,
- a **status line** in the settings (songs analyzed, text index, running analysis).

It runs next to Music Assistant's other similarity sources (Last.fm, Sonic Similarity). It is
a *metadata* provider: Music Assistant asks metadata providers for similar tracks before
plugin providers, sorted by priority. With priority 10 it is asked before Last.fm (50) and
Sonic Similarity (plugin), and Music Assistant falls back to those when AudioMuse-AI has no
answer or is unreachable.

> Status: **alpha**. Tested against a fake AudioMuse-AI server; first runs against a real
> Music Assistant 2.10 / AudioMuse-AI setup are pending.

## How it fits together

AudioMuse-AI normally analyzes music through Jellyfin, Navidrome, Plex, Emby or Lyrion.
This plugin expects AudioMuse-AI to analyze the **Music Assistant library itself**, using the
`musicassistant` server type from
[Styx85/AudioMuse-AI, branch `music-assistant-server`](https://github.com/Styx85/AudioMuse-AI/tree/music-assistant-server)
(proposed upstream). With that, AudioMuse-AI's track ids *are* Music Assistant library ids,
so no matching between two libraries is needed:

```
Music Assistant ──(JSON API: library, playlists)──► AudioMuse-AI ◄── shared music folder (read-only)
      ▲                                                 │
      └──── this plugin: /api/similar_tracks?item_id=<MA library id> ──┘
```

AudioMuse-AI reads the audio of Music Assistant's local **filesystem** providers straight
from a shared folder; Music Assistant has (by design) no download endpoint. Streaming-service
tracks are not analyzed. If a seed track is unknown to AudioMuse-AI, the plugin can fall back
to asking by artist and title.

## Install (manual, until it is part of Music Assistant)

Music Assistant only loads providers from its own package folder. For the Docker image,
mount both folders of this repo into it, e.g. in `compose.yml`:

```yaml
    volumes:
      - ./music-assistant-audiomuse/audiomuse:/app/venv/lib/python3.14/site-packages/music_assistant/providers/audiomuse:ro
      - ./music-assistant-audiomuse/audiomuse_search:/app/venv/lib/python3.14/site-packages/music_assistant/providers/audiomuse_search:ro
```

`audiomuse_search` is optional. It exists because Music Assistant's global search only asks
plugin providers, while the main provider must be a metadata provider (see above). It has no
settings and uses the main provider's connection.

Check the Python version in the path for your image (`docker exec music-assistant ls /app/venv/lib`).
Restart Music Assistant, then add **AudioMuse-AI** under *Settings → Providers* (metadata)
and, for text search, **AudioMuse-AI Text Search** (plugin).

### Setup

- **AudioMuse-AI URL**, e.g. `http://audiomuse:8000`
- **API token**: AudioMuse-AI's `API_TOKEN` (stored encrypted)
- **AudioMuse-AI music server** (advanced): leave empty if the Music Assistant server is
  AudioMuse-AI's default server, otherwise its name

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| Ask AudioMuse-AI first | on | priority 10 (before Last.fm and Sonic Similarity), otherwise 60 |
| Limit songs per artist | AudioMuse-AI default | AudioMuse-AI `eliminate_duplicates` |
| Also match mood | AudioMuse-AI default | AudioMuse-AI `mood_similarity` |
| Look up unmatched tracks by artist and title | on | fallback for unknown seeds |
| Show "Inspired by recently played" | on | discover row from the last 5 played tracks (cached 5 min) |

## Behaviour and errors

- Asks AudioMuse-AI for `2 × limit + 1` neighbours (max 200), drops the seed and duplicates,
  loads the results from the library and skips ids that are no longer there.
- Unreachable AudioMuse-AI, bad token, timeouts, 5xx → `ProviderUnavailableError`, so
  Music Assistant logs it and uses the next similarity provider.
- Unknown seed (404) → artist/title fallback, otherwise an empty result.
- Error messages from AudioMuse-AI are passed on with the API token redacted.

## Roadmap

1. Similar tracks / radio / autoplay, discover row, free-text search, status (this release)
2. More similarity options (radius walk, mood anchors), song path between two tracks
3. Alchemy, sonic fingerprint, mood playlists

## Development

```bash
pip install aiohttp pytest
python -m pytest -q
```

The tests run without Music Assistant: the package is loaded without its `__init__.py`, and a
fake AudioMuse-AI server (aiohttp) covers auth, parameters, errors and parsing. `provider.py`
and `setup_flow.py` need a Music Assistant development environment
(see Music Assistant's `DEVELOPMENT.md`) and are not covered yet.

Code style follows Music Assistant (`AGENTS.md`): Sphinx docstrings, line length 100.

## License

Apache-2.0, like Music Assistant. This plugin only talks to AudioMuse-AI over HTTP and
contains no AudioMuse-AI code (AudioMuse-AI is AGPL-3.0).
