# AudioMuse-AI for Music Assistant

[Music Assistant](https://music-assistant.io) providers that bring a self-hosted
[AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI) sonic analysis server into Music
Assistant: similar tracks for **radio mode** and **autoplay**, **discover rows** (inspired by
recently played, moods, alchemy), **free-text search** by sound ("calm piano in the evening")
and **song paths** between two tracks.

## Status

**Alpha**, running on one home setup (Music Assistant 2.10.9, AudioMuse-AI 3.7.1).

| Feature | State |
| --- | --- |
| Similar tracks / radio / autoplay | working against a real Music Assistant; results from AudioMuse-AI once its first analysis has built the index |
| Ranked fallback (e.g. Sonic Similarity, Last.fm, Spotify) | working |
| Discover row "Inspired by recently played" | working |
| Mood rows (happy, relaxed, danceable, party, energetic, melancholic) | working, hidden by default |
| Alchemy rows (one per anchor saved in AudioMuse-AI) | working |
| Smooth radio (AudioMuse-AI radius similarity) | option |
| Song path | API commands `audiomuse/song_path`, `audiomuse/song_path_playlist` |
| Free-text search (`audiomuse_search`) | working |
| Status line, English and German UI | working |
| Song path / alchemy buttons inside Music Assistant's UI | not possible without UI changes in Music Assistant; use the API commands or AudioMuse-AI's own UI (its playlists land in Music Assistant) |

Needs AudioMuse-AI with the **Music Assistant server type**, which is not upstream yet:
[Styx85/AudioMuse-AI, branch `music-assistant-server`](https://github.com/Styx85/AudioMuse-AI/tree/music-assistant-server)
(planned as a pull request to AudioMuse-AI).

## Concept

```
Music Assistant ──(JSON API: library, playlists, play counts)──► AudioMuse-AI
      ▲                                                          │  reads audio from the
      │   similar tracks / search / discover                     │  shared music folder
      └──────────── these providers ◄──── library ids ───────────┘  (read-only)
```

- **AudioMuse-AI analyzes the Music Assistant library directly** (server type
  `musicassistant`): it lists tracks through Music Assistant's API and reads the audio of the
  local filesystem providers from the same music folder. No Jellyfin, Navidrome or Plex in
  between, and AudioMuse-AI's track ids *are* Music Assistant library ids, so no matching.
- **`audiomuse`** (metadata provider) answers *similar tracks*. Music Assistant asks metadata
  providers before plugins, by priority; with priority 10 AudioMuse-AI comes before Last.fm
  (50) and Sonic Similarity (plugin). Without an answer from AudioMuse-AI it asks your ranked
  fallbacks (default: Sonic Similarity); only if all are empty does Music Assistant continue
  with its remaining providers.
- **`audiomuse_search`** (plugin) adds free-text search: Music Assistant's global search only
  asks plugin providers. It has no settings and uses the main provider's connection.
- Streaming-service tracks are not analyzed (Music Assistant has, by design, no download
  endpoint). For them the provider can fall back to asking AudioMuse-AI by artist and title.

## Installation

### 1. AudioMuse-AI with the Music Assistant server type

Run AudioMuse-AI (Flask, worker, PostgreSQL; ~8 GB RAM, AVX2) from the fork above, e.g. by
layering the fork's code over the official 3.7.1 image:

```dockerfile
FROM ghcr.io/neptunehub/audiomuse-ai:3.7.1
COPY . /app
```

```bash
git clone --branch music-assistant-server https://github.com/Styx85/AudioMuse-AI.git src
docker build -f Dockerfile -t audiomuse-ai-ma:local src
```

Use `audiomuse-ai-ma:local` for the `audiomuse-ai-flask` and `audiomuse-ai-worker` services of
AudioMuse-AI's `deployment/docker-compose.yaml`, and mount the music folder of Music
Assistant's filesystem provider into **both** services, read-only:

```yaml
    volumes:
      - /path/to/music:/music:ro
```

Set `API_TOKEN` in AudioMuse-AI (the providers authenticate with it).

### 2. Connect AudioMuse-AI to Music Assistant

1. In Music Assistant create a long-lived access token (your profile → tokens).
2. In AudioMuse-AI: *Setup → Music Servers → add* type **Music Assistant** with
   URL `http://<music-assistant>:8095`, the token and music folder `/music`.
   *Test connection* warns if the files are not readable.
3. Start an analysis (for a first test e.g. only the 50 most recent albums). AudioMuse-AI builds
   its similarity index at the end of the run.

### 3. Install the providers in Music Assistant

Music Assistant only loads providers from its own package folder. With the Docker image, clone
this repository next to your `compose.yml` and mount both folders:

```bash
git clone https://github.com/Styx85/music-assistant-audiomuse.git providers-src/audiomuse
```

```yaml
    volumes:
      - ./providers-src/audiomuse/audiomuse:/app/venv/lib/python3.14/site-packages/music_assistant/providers/audiomuse:ro
      - ./providers-src/audiomuse/audiomuse_search:/app/venv/lib/python3.14/site-packages/music_assistant/providers/audiomuse_search:ro
```

Check the Python version in the path (`docker exec music-assistant ls /app/venv/lib`), then
`docker compose up -d`. Update later with `git -C providers-src/audiomuse pull` and a restart.

### 4. Set up the providers

- *Settings → Providers → add* **AudioMuse-AI** (metadata): URL `http://<audiomuse>:8000`,
  API token = AudioMuse-AI's `API_TOKEN`.
- Optionally add **AudioMuse-AI Text Search** (plugin) for free-text search.

| Option | Default | |
| --- | --- | --- |
| Ask AudioMuse-AI first | on | priority 10 (before Last.fm), otherwise 60 |
| Fallback 1 / 2 / 3 | Sonic Similarity / none / none | ranked sources when AudioMuse-AI has no answer |
| Smooth radio (fewer jumps) | AudioMuse-AI default | radius similarity: the radio drifts gradually |
| Show "Inspired by recently played" | on | discover row from your last 5 played tracks |
| Show mood rows / alchemy rows | on | rows on the discover page (mood rows start hidden there) |
| Limit songs per artist, Also match mood | AudioMuse-AI default | passed to AudioMuse-AI |
| Look up unmatched tracks by artist and title | on | for tracks AudioMuse-AI does not know |

## Song path

Music Assistant has no UI to pick two tracks, so song paths are API commands (e.g. for scripts
or automations), taking Music Assistant library ids:

```json
{"command": "audiomuse/song_path_playlist",
 "args": {"start_item_id": "51977", "end_item_id": "5", "max_steps": 15}}
```

`audiomuse/song_path` returns the tracks; `audiomuse/song_path_playlist` also saves them as a
playlist ("Song path: A → B" unless `name` is given). Paths and alchemy playlists built in
AudioMuse-AI's own web UI are created as Music Assistant playlists as well.

## Development

```bash
pip install aiohttp pytest
python -m pytest -q
```

Tests run without Music Assistant against a fake AudioMuse-AI server. `provider.py`,
`setup_flow.py` and the `__init__` modules need a Music Assistant development environment and
are verified on a live install. Code style follows Music Assistant (Sphinx docstrings, line
length 100).

Until the providers are part of Music Assistant, they register their texts (English, German) in
Music Assistant's translation controller at runtime, because Music Assistant only compiles
translations of built-in providers.

## License

Apache-2.0, like Music Assistant. The providers only talk to AudioMuse-AI over HTTP and contain
no AudioMuse-AI code (AudioMuse-AI is AGPL-3.0). The icons are AudioMuse-AI's logo, used to
identify the integration.
