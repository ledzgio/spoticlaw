# Spoticlaw

Lightweight Spotify Web API client for AI agents.

## Features

- **No external dependencies** (uses direct HTTP requests)
- **Automatic token refresh** — authenticate once, works forever
- **Composable primitives** — mix and match to build complex workflows
- Full Spotify Web API coverage
- Lightweight and fast

## Composable Primitives

Combine primitives to create powerful workflows:

```python
# Example: Find an artist → get their albums → create playlist → add top tracks
artist = search().query("metallica", types=["artist"])[0]
albums = artists().get_albums(artist["id"], limit=10)
track_uris = [albums["items"][0]["tracks"]["items"][0]["uri"]]
pl = playlists().create(f"{artist['name']} Mix")
playlists().add_items(pl["id"], track_uris)
```

The primitives are designed to be combined in endless ways for any Spotify automation task.

## Setup

1. Install dependencies:
```bash
cd skills/spoticlaw/scripts
pip install -r requirements.txt
```

2. Configure Spotify credentials:
```bash
cp .env.example .env
# Edit .env with your Spotify app credentials
```

3. Get credentials from https://developer.spotify.com/dashboard

4. Authenticate:
```bash
python auth.py
```

**That's it!** Token auto-refreshes — no need to re-authenticate.

## Quick Usage

```python
from spoticlaw import player, search, playlists, library

# Search
search().query("coldplay", types=["track"], limit=10)

# Play
player().play(uris=["spotify:track:..."])

# Playlists
playlists().create("My Playlist")
playlists().add_items("playlist_id", ["spotify:track:..."])

# Library
library().save(["spotify:track:..."])
```

## Token Refresh

The library automatically refreshes your access token when it expires (every 60 minutes). No user interaction needed after initial authentication.

If you get a token error, re-run:
```bash
python auth.py
```

## Requirements

- Python 3.8+
- requests
- python-dotenv

## License

MIT
