"""
Spoticlaw v2 - Spotify Web API Client using direct HTTP requests.

Implements all endpoints available as of Spotify's February 2026 API changes.
Reference: https://developer.spotify.com/documentation/web-api
"""

import os
import json
import time
from pathlib import Path
from functools import lru_cache
from typing import Any, Optional

import requests
from dotenv import load_dotenv

try:
    from .memory import load_memory, save_memory, record_play, set_track_feedback, get_recent_plays, get_all_genres, get_history_artists
except Exception:
    from memory import load_memory, save_memory, record_play, set_track_feedback, get_recent_plays, get_all_genres, get_history_artists  # type: ignore

try:
    from .lastfm import get_similar_artists as _lfm_similar, get_artist_tags as _lfm_tags
except Exception:
    try:
        from lastfm import get_similar_artists as _lfm_similar, get_artist_tags as _lfm_tags  # type: ignore
    except Exception:
        _lfm_similar = None
        _lfm_tags = None

# Load .env
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

# Configuration
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
CACHE_PATH = os.getenv("SPOTIFY_CACHE_PATH", ".spotify_cache")

BASE_URL = "https://api.spotify.com/v1"

# Optional features are disabled by default unless explicitly enabled in .env
LASTFM_ENABLED = os.getenv("LASTFM_ENABLED", "false").lower() in ("1", "true", "yes", "on")


class SpotifyException(Exception):
    """Spotify API exception."""
    pass


def _memory_record_play_safe(
    track_uri: str,
    artist_uri: str | None = None,
    album_uri: str | None = None,
    track_name: str | None = None,
    artist_name: str | None = None,
    album_name: str | None = None,
    source: str = "unknown",
    enrich: bool = True,
) -> None:
    """Best-effort memory logging; never breaks playback.

    If enrich=True and Last.fm is enabled, also stores Last.fm tags/similar artists
    on the aggregated track record.
    """
    try:
        mem = load_memory()

        record_play(
            mem,
            track_uri=track_uri,
            artist_uri=artist_uri,
            album_uri=album_uri,
            track_name=track_name,
            artist_name=artist_name,
            album_name=album_name,
            source=source,
        )

        # Enrich with Last.fm only when explicitly enabled and artist is known
        if enrich and LASTFM_ENABLED and _lfm_tags and artist_name:
            try:
                tags_result = _lfm_tags(artist_name)
                tags = [t.get("name") for t in tags_result.get("tags", [])[:5]]

                similar_result = _lfm_similar(artist_name, limit=5) if _lfm_similar else {}
                similar = [s.get("name") for s in similar_result.get("similar", [])[:5]]

                tracks = mem.get("tracks") if isinstance(mem.get("tracks"), dict) else {}
                rec = tracks.get(track_uri) if isinstance(tracks, dict) else None
                if isinstance(rec, dict):
                    if tags:
                        rec["lastfm_tags"] = list(dict.fromkeys([str(x) for x in tags if x]))
                    if similar:
                        rec["similar_artists"] = list(dict.fromkeys([str(x) for x in similar if x]))
            except Exception:
                pass  # Best-effort enrichment

        save_memory(mem)
    except Exception:
        pass


# ============================================================================
# Token Management with Auto-Refresh
# ============================================================================

def _get_cache_path() -> Path:
    """Get path to cache file."""
    return Path(__file__).parent.parent / CACHE_PATH


def _load_token_data() -> dict:
    """Load token data from cache."""
    cache_file = _get_cache_path()
    if not cache_file.exists():
        raise SpotifyException("No token. Re-authenticate: run auth.py")
    with open(cache_file) as f:
        return json.load(f)


def _save_token_data(data: dict) -> None:
    """Save token data to cache."""
    cache_file = _get_cache_path()
    with open(cache_file, "w") as f:
        json.dump(data, f)


def _is_token_expired(token_data: dict) -> bool:
    """Check if token is expired."""
    expires_at = token_data.get("expires_at", 0)
    # Add 60 second buffer to be safe
    return time.time() >= (expires_at - 60)


def _refresh_token() -> str:
    """Refresh access token using refresh_token."""
    token_data = _load_token_data()
    refresh_token = token_data.get("refresh_token")
    
    if not refresh_token:
        raise SpotifyException("No refresh_token. Re-authenticate: run auth.py")
    
    # Encode client credentials
    import base64
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    # Request new token
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    )
    
    if resp.status_code != 200:
        raise SpotifyException(f"Token refresh failed: {resp.status_code} - {resp.text}")
    
    new_token_data = resp.json()
    
    # Keep the old refresh_token if not returned
    if "refresh_token" not in new_token_data:
        new_token_data["refresh_token"] = refresh_token
    
    # Calculate expires_at
    new_token_data["expires_at"] = time.time() + new_token_data.get("expires_in", 3600)
    
    # Save new token data
    _save_token_data(new_token_data)
    
    print("🔄 Token refreshed automatically")
    return new_token_data.get("access_token")


def _get_token() -> str:
    """Get valid access token (auto-refreshes if expired)."""
    token_data = _load_token_data()
    
    # Check if token is expired and refresh if needed
    if _is_token_expired(token_data):
        return _refresh_token()
    
    return token_data.get("access_token")


def _headers() -> dict:
    """Get headers with auth."""
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def get(endpoint: str, **params) -> dict:
    """GET request to Spotify API."""
    url = f"{BASE_URL}{endpoint}"
    resp = requests.get(url, headers=_headers(), params=params)
    
    # If unauthorized, try refreshing token once
    if resp.status_code == 401:
        _refresh_token()
        resp = requests.get(url, headers=_headers(), params=params)
    
    if resp.status_code == 204:
        return {}  # No content
    if resp.status_code not in (200, 201):
        raise SpotifyException(f"GET {endpoint}: {resp.status_code} - {resp.text}")
    return resp.json() if resp.text else {}


def post(endpoint: str, **payload) -> dict:
    """POST request to Spotify API."""
    url = f"{BASE_URL}{endpoint}"
    resp = requests.post(url, headers=_headers(), json=payload if payload else None)
    
    # If unauthorized, try refreshing token once
    if resp.status_code == 401:
        _refresh_token()
        resp = requests.post(url, headers=_headers(), json=payload if payload else None)
    
    if resp.status_code == 204 or resp.status_code == 200:
        return {}  # No content or empty success response
    if resp.status_code not in (200, 201):
        raise SpotifyException(f"POST {endpoint}: {resp.status_code} - {resp.text}")
    return resp.json() if resp.text else {}


def put(endpoint: str, **payload) -> dict:
    """PUT request to Spotify API."""
    url = f"{BASE_URL}{endpoint}"
    resp = requests.put(url, headers=_headers(), json=payload if payload else None)
    
    # If unauthorized, try refreshing token once
    if resp.status_code == 401:
        _refresh_token()
        resp = requests.put(url, headers=_headers(), json=payload if payload else None)
    
    if resp.status_code == 204 or resp.status_code == 200:
        return {}  # No content or empty success response
    if resp.status_code not in (200, 204):
        raise SpotifyException(f"PUT {endpoint}: {resp.status_code} - {resp.text}")
    return resp.json() if resp.text else {}


def delete(endpoint: str, **payload) -> dict:
    """DELETE request to Spotify API."""
    url = f"{BASE_URL}{endpoint}"
    resp = requests.delete(url, headers=_headers(), json=payload)
    
    # If unauthorized, try refreshing token once
    if resp.status_code == 401:
        _refresh_token()
        resp = requests.delete(url, headers=_headers(), json=payload)
    
    if resp.status_code not in (200, 204):
        raise SpotifyException(f"DELETE {endpoint}: {resp.status_code} - {resp.text}")
    return resp.json() if resp.text else {}


# ============================================================================
# User Endpoints
# ============================================================================

class User:
    """User endpoints."""
    
    @staticmethod
    def me() -> dict:
        """Get current user's profile."""
        return get("/me")


# ============================================================================
# Library Endpoints (NEW /me/library API)
# ============================================================================

class Library:
    """Library endpoints."""
    
    @staticmethod
    def save(uris: list[str]) -> dict:
        """Save items to user's library."""
        url = f"{BASE_URL}/me/library"
        resp = requests.put(url, headers=_headers(), params={"uris": ",".join(uris)})
        if resp.status_code not in (200, 204):
            raise SpotifyException(f"Library save: {resp.status_code} - {resp.text}")
        return {}
    
    @staticmethod
    def remove(uris: list[str]) -> dict:
        """Remove items from user's library."""
        url = f"{BASE_URL}/me/library"
        resp = requests.delete(url, headers=_headers(), params={"uris": ",".join(uris)})
        if resp.status_code not in (200, 204):
            raise SpotifyException(f"Library remove: {resp.status_code} - {resp.text}")
        return {}
    
    @staticmethod
    def check(uris: list[str]) -> list[bool]:
        """Check if items are in user's library."""
        url = f"{BASE_URL}/me/library/contains?uris={','.join(uris)}"
        resp = requests.get(url, headers=_headers())
        if resp.status_code != 200:
            raise SpotifyException(f"Library check: {resp.status_code} - {resp.text}")
        return resp.json()


# ============================================================================
# Playlist Endpoints
# ============================================================================

class Playlists:
    """Playlist endpoints."""
    
    @staticmethod
    def get(playlist_id: str) -> dict:
        """Get playlist details."""
        return get(f"/playlists/{playlist_id}")
    
    @staticmethod
    def get_items(playlist_id: str, limit: int = 50, offset: int = 0) -> dict:
        """Get playlist items (tracks/episodes)."""
        return get(f"/playlists/{playlist_id}/items", limit=limit, offset=offset)
    
    @staticmethod
    def get_cover(playlist_id: str) -> list[dict]:
        """Get playlist cover image."""
        return get(f"/playlists/{playlist_id}/images")
    
    @staticmethod
    def create(name: str, description: str = "", public: bool = False) -> dict:
        """Create new playlist."""
        return post("/me/playlists", name=name, description=description, public=public)
    
    @staticmethod
    def update(playlist_id: str, name: str = None, description: str = None, public: bool = None) -> dict:
        """Update playlist details."""
        payload = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if public is not None:
            payload["public"] = public
        return put(f"/playlists/{playlist_id}", **payload)
    
    @staticmethod
    def add_items(playlist_id: str, uris: list[str], position: int = None) -> dict:
        """Add items to playlist."""
        payload = {"uris": uris}
        if position is not None:
            payload["position"] = position
        return post(f"/playlists/{playlist_id}/items", **payload)
    
    @staticmethod
    def remove_items(playlist_id: str, uris: list[str], snapshot_id: str = None) -> dict:
        """Remove items from playlist."""
        tracks = [{"uri": uri} for uri in uris]
        payload = {"tracks": tracks}
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        return delete(f"/playlists/{playlist_id}/items", **payload)
    
    @staticmethod
    def update_items(playlist_id: str, range_start: int, insert_before: int, range_length: int = 1, snapshot_id: str = None) -> dict:
        """Reorder items in playlist."""
        payload = {
            "range_start": range_start,
            "insert_before": insert_before,
            "range_length": range_length
        }
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        return put(f"/playlists/{playlist_id}/items", **payload)
    
    @staticmethod
    def replace_items(playlist_id: str, uris: list[str]) -> dict:
        """Replace all items in playlist."""
        return put(f"/playlists/{playlist_id}/items", uris=uris)
    
    @staticmethod
    def upload_cover(playlist_id: str, image_base64: str) -> dict:
        """Upload custom playlist cover image."""
        url = f"{BASE_URL}/playlists/{playlist_id}/images"
        resp = requests.put(url, headers={"Authorization": f"Bearer {_get_token()}", "Content-Type": "image/jpeg"}, data=image_base64)
        if resp.status_code not in (200, 201):
            raise SpotifyException(f"Upload cover: {resp.status_code} - {resp.text}")
        return {}


class UserPlaylists:
    """User's playlists endpoints."""
    
    @staticmethod
    def get(limit: int = 50, offset: int = 0) -> dict:
        """Get current user's playlists."""
        return get("/me/playlists", limit=limit, offset=offset)


# ============================================================================
# Player Endpoints
# ============================================================================

class Player:
    """Player endpoints."""
    
    @staticmethod
    def get_playback_state() -> dict:
        """Get playback state."""
        return get("/me/player")
    
    @staticmethod
    def get_currently_playing() -> dict:
        """Get currently playing track."""
        return get("/me/player/currently-playing")
    
    @staticmethod
    def get_devices() -> dict:
        """Get available devices."""
        return get("/me/player/devices")
    
    @staticmethod
    def get_recently_played(limit: int = 50) -> dict:
        """Get recently played tracks."""
        return get("/me/player/recently-played", limit=limit)
    
    @staticmethod
    def get_queue() -> dict:
        """Get playback queue."""
        return get("/me/player/queue")
    
    @staticmethod
    def play(device_id: str = None, context_uri: str = None, uris: list[str] = None, offset: int = 0, position_ms: int = 0) -> dict:
        """Start/resume playback."""
        payload = {}
        if context_uri:
            payload["context_uri"] = context_uri
            payload["offset"] = {"position": offset}
        if uris:
            payload["uris"] = uris
        if position_ms:
            payload["position_ms"] = position_ms
        
        params = f"?device_id={device_id}" if device_id else ""
        out = put(f"/me/player/play{params}", **payload)

        # best-effort memory log for direct-track play calls (only if we got track details)
        try:
            if uris and len(uris) > 0:
                track_uri = uris[0]
                track_name = None
                artist_name = None
                if track_uri.startswith("spotify:track:"):
                    tid = track_uri.split(":")[-1]
                    try:
                        t = tracks().get(tid)
                        track_name = t.get("name")
                        artists = t.get("artists") or []
                        if artists:
                            artist_name = artists[0].get("name")
                    except Exception:
                        pass
                # Only log if we got track details
                if track_name and artist_name:
                    _memory_record_play_safe(track_uri=track_uri, track_name=track_name, artist_name=artist_name, source="play")
        except Exception:
            pass

        return out
    
    @staticmethod
    def pause(device_id: str = None) -> dict:
        """Pause playback."""
        params = f"?device_id={device_id}" if device_id else ""
        return put(f"/me/player/pause{params}")
    
    @staticmethod
    def seek(position_ms: int, device_id: str = None) -> dict:
        """Seek to position."""
        params = f"position_ms={position_ms}"
        if device_id:
            params += f"&device_id={device_id}"
        return put(f"/me/player/seek?{params}")
    
    @staticmethod
    def set_volume(volume_percent: int, device_id: str = None) -> dict:
        """Set volume."""
        params = f"volume_percent={volume_percent}"
        if device_id:
            params += f"&device_id={device_id}"
        return put(f"/me/player/volume?{params}")
    
    @staticmethod
    def set_repeat(state: str, device_id: str = None) -> dict:
        """Set repeat mode (off, track, context)."""
        params = f"state={state}"
        if device_id:
            params += f"&device_id={device_id}"
        return put(f"/me/player/repeat?{params}")
    
    @staticmethod
    def set_shuffle(state: bool, device_id: str = None) -> dict:
        """Set shuffle mode."""
        params = f"state={str(state).lower()}"
        if device_id:
            params += f"&device_id={device_id}"
        return put(f"/me/player/shuffle?{params}")
    
    @staticmethod
    def next(device_id: str = None) -> dict:
        """Skip to next track."""
        params = f"?device_id={device_id}" if device_id else ""
        return post(f"/me/player/next{params}")
    
    @staticmethod
    def previous(device_id: str = None) -> dict:
        """Skip to previous track."""
        params = f"?device_id={device_id}" if device_id else ""
        return post(f"/me/player/previous{params}")
    
    @staticmethod
    def add_to_queue(uri: str, device_id: str = None) -> dict:
        """Add item to queue."""
        params = f"uri={uri}"
        if device_id:
            params += f"&device_id={device_id}"
        
        # Queue endpoint returns 204 with empty body - use direct request
        url = f"{BASE_URL}/me/player/queue?{params}"
        resp = requests.post(url, headers=_headers())
        
        # If unauthorized, try refreshing token once
        if resp.status_code == 401:
            _refresh_token()
            resp = requests.post(url, headers=_headers())
        
        if resp.status_code == 204 or resp.status_code == 200:
            # Try to get track details for enrichment (only log if we got them)
            track_name = None
            artist_name = None
            if uri.startswith("spotify:track:"):
                tid = uri.split(":")[-1]
                try:
                    t = tracks().get(tid)
                    track_name = t.get("name")
                    artists = t.get("artists") or []
                    if artists:
                        artist_name = artists[0].get("name")
                except Exception:
                    pass
            # Only log if we got track details
            if track_name and artist_name:
                _memory_record_play_safe(track_uri=uri, track_name=track_name, artist_name=artist_name, source="add_to_queue")
            return {}
        if resp.status_code not in (200, 201):
            raise SpotifyException(f"add_to_queue: {resp.status_code} - {resp.text}")
        return resp.json() if resp.text else {}
    
    @staticmethod
    def transfer(device_id: str, play: bool = True) -> dict:
        """Transfer playback to device."""
        return put("/me/player", device_ids=[device_id], play=play)


# ============================================================================
# Search Endpoints
# ============================================================================

class Search:
    """Search endpoint."""
    
    @staticmethod
    def query(q: str, types: list[str], market: str = None, limit: int = 10, offset: int = 0) -> dict:
        """
        Search for items.
        
        Args:
            q: Search query.
            types: List of types: track, artist, album, playlist, show, episode, audiobook.
            market: Country code.
            limit: Max results (1-10).
            offset: Pagination offset.
        """
        return get("/search", q=q, type=",".join(types), market=market, limit=limit, offset=offset)


# ============================================================================
# Track Endpoints
# ============================================================================

class Tracks:
    """Track endpoints."""
    
    @staticmethod
    def get(track_id: str) -> dict:
        """Get track details."""
        return get(f"/tracks/{track_id}")
    
    @staticmethod
    def get_multiple(ids: list[str]) -> dict:
        """Get multiple tracks."""
        return get("/tracks", ids=",".join(ids))


# ============================================================================
# Artist Endpoints
# ============================================================================

class Artists:
    """Artist endpoints."""
    
    @staticmethod
    def get(artist_id: str) -> dict:
        """Get artist details."""
        return get(f"/artists/{artist_id}")
    
    @staticmethod
    def get_multiple(ids: list[str]) -> dict:
        """Get multiple artists."""
        return get("/artists", ids=",".join(ids))
    
    @staticmethod
    def get_albums(artist_id: str, include_groups: str = None, market: str = None, limit: int = 20, offset: int = 0) -> dict:
        """Get artist's albums."""
        params = {"limit": limit, "offset": offset}
        if include_groups:
            params["include_groups"] = include_groups
        if market:
            params["market"] = market
        return get(f"/artists/{artist_id}/albums", **params)


# ============================================================================
# Album Endpoints
# ============================================================================

class Albums:
    """Album endpoints."""
    
    @staticmethod
    def get(album_id: str) -> dict:
        """Get album details."""
        return get(f"/albums/{album_id}")
    
    @staticmethod
    def get_multiple(ids: list[str]) -> dict:
        """Get multiple albums."""
        return get("/albums", ids=",".join(ids))
    
    @staticmethod
    def get_tracks(album_id: str, limit: int = 50, offset: int = 0) -> dict:
        """Get album tracks."""
        return get(f"/albums/{album_id}/tracks", limit=limit, offset=offset)


# ============================================================================
# Show Endpoints (Podcasts)
# ============================================================================

class Shows:
    """Podcast show endpoints."""
    
    @staticmethod
    def get(show_id: str) -> dict:
        """Get show details."""
        return get(f"/shows/{show_id}")
    
    @staticmethod
    def get_multiple(ids: list[str]) -> dict:
        """Get multiple shows."""
        return get("/shows", ids=",".join(ids))
    
    @staticmethod
    def get_episodes(show_id: str, limit: int = 50, offset: int = 0) -> dict:
        """Get show episodes."""
        return get(f"/shows/{show_id}/episodes", limit=limit, offset=offset)


# ============================================================================
# Episode Endpoints (Podcasts)
# ============================================================================

class Episodes:
    """Podcast episode endpoints."""
    
    @staticmethod
    def get(episode_id: str) -> dict:
        """Get episode details."""
        return get(f"/episodes/{episode_id}")
    
    @staticmethod
    def get_multiple(ids: list[str]) -> dict:
        """Get multiple episodes."""
        return get("/episodes", ids=",".join(ids))


# ============================================================================
# Audiobook Endpoints
# ============================================================================

class Audiobooks:
    """Audiobook endpoints."""
    
    @staticmethod
    def get(audiobook_id: str) -> dict:
        """Get audiobook details."""
        return get(f"/audiobooks/{audiobook_id}")
    
    @staticmethod
    def get_multiple(ids: list[str]) -> dict:
        """Get multiple audiobooks."""
        return get("/audiobooks", ids=",".join(ids))
    
    @staticmethod
    def get_chapters(audiobook_id: str, limit: int = 50, offset: int = 0) -> dict:
        """Get audiobook chapters."""
        return get(f"/audiobooks/{audiobook_id}/chapters", limit=limit, offset=offset)


# ============================================================================
# Chapter Endpoints
# ============================================================================

class Chapters:
    """Chapter endpoints."""
    
    @staticmethod
    def get(chapter_id: str) -> dict:
        """Get chapter details."""
        return get(f"/chapters/{chapter_id}")


# ============================================================================
# Follow Endpoints
# ============================================================================

class Follow:
    """Follow endpoints."""
    
    @staticmethod
    def get_followed(type: str = "artist", limit: int = 50, after: str = None) -> dict:
        """Get followed artists."""
        params = {"type": type, "limit": limit}
        if after:
            params["after"] = after
        return get("/me/following", **params)


# ============================================================================
# Personalisation Endpoints
# ============================================================================

class Personalisation:
    """Personalisation endpoints."""
    
    @staticmethod
    def get_top(type: str, time_range: str = "medium_term", limit: int = 20, offset: int = 0) -> dict:
        """Get user's top artists or tracks."""
        return get(f"/me/top/{type}", time_range=time_range, limit=limit, offset=offset)


# ============================================================================
# Convenience Functions
# ============================================================================

@lru_cache(maxsize=1)
def user() -> User:
    return User()


@lru_cache(maxsize=1)
def library() -> Library:
    return Library()


@lru_cache(maxsize=1)
def playlists() -> Playlists:
    return Playlists()


@lru_cache(maxsize=1)
def user_playlists() -> UserPlaylists:
    return UserPlaylists()


@lru_cache(maxsize=1)
def player() -> Player:
    return Player()


@lru_cache(maxsize=1)
def search() -> Search:
    return Search()


@lru_cache(maxsize=1)
def tracks() -> Tracks:
    return Tracks()


@lru_cache(maxsize=1)
def artists() -> Artists:
    return Artists()


@lru_cache(maxsize=1)
def albums() -> Albums:
    return Albums()


@lru_cache(maxsize=1)
def shows() -> Shows:
    return Shows()


@lru_cache(maxsize=1)
def episodes() -> Episodes:
    return Episodes()


@lru_cache(maxsize=1)
def audiobooks() -> Audiobooks:
    return Audiobooks()


@lru_cache(maxsize=1)
def chapters() -> Chapters:
    return Chapters()


@lru_cache(maxsize=1)
def follow() -> Follow:
    return Follow()


@lru_cache(maxsize=1)
def personalisation() -> Personalisation:
    return Personalisation()


def memory_add_song(
    track_uri: str,
    artist_uri: str | None = None,
    album_uri: str | None = None,
    track_name: str | None = None,
    artist_name: str | None = None,
    album_name: str | None = None,
    source: str = "manual",
    user_rating: int | None = None,
    mood_tags: list[str] | None = None,
) -> dict:
    """Add/update an aggregated track memory record."""
    mem = load_memory()
    record_play(
        mem,
        track_uri=track_uri,
        artist_uri=artist_uri,
        album_uri=album_uri,
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        source=source,
        user_rating=user_rating,
        mood_tags=mood_tags,
    )
    save_memory(mem)
    tracks = mem.get("tracks") if isinstance(mem.get("tracks"), dict) else {}
    return {
        "ok": True,
        "track": tracks.get(track_uri) if isinstance(tracks, dict) else None,
    }


def memory_set_feedback(track_uri: str, user_rating: int | None = None, mood_tags: list[str] | None = None) -> dict:
    """Set explicit user feedback for a tracked song.

    - user_rating: optional int 1..10
    - mood_tags: optional list of string labels
    """
    mem = load_memory()
    rec = set_track_feedback(mem, track_uri=track_uri, user_rating=user_rating, mood_tags=mood_tags)
    if rec is None:
        return {"ok": False, "reason": "track not found in memory"}
    save_memory(mem)
    return {"ok": True, "track": rec}


def discover_similar_artists(seed_artist: str, limit: int = 10) -> dict:
    """Find similar artists using Last.fm API.

    Args:
        seed_artist: Artist name or Spotify ID
        limit: Max artists to return

    Returns:
        {"seed": {...}, "artists": [...]}
    """
    if not LASTFM_ENABLED:
        return {"seed": None, "artists": [], "reason": "LASTFM is disabled (set LASTFM_ENABLED=true)"}
    if not _lfm_similar:
        return {"seed": None, "artists": [], "reason": "LASTFM_API_KEY not configured"}

    # Resolve seed artist
    seed_obj = None
    if len(seed_artist) == 22 and seed_artist.isalnum():
        try:
            seed_obj = artists().get(seed_artist)
        except Exception:
            seed_obj = None
    if not seed_obj:
        search_term = seed_artist.strip('"').strip("'")
        res = search().query(search_term, types=["artist"], limit=5)
        items = (res.get("artists") or {}).get("items") or []
        if not items:
            return {"seed": None, "artists": [], "reason": "Seed artist not found."}
        search_lower = search_term.lower()
        for item in items:
            if item.get("name", "").lower() == search_lower:
                seed_obj = item
                break
        if not seed_obj:
            seed_obj = items[0]

    seed_name = seed_obj.get("name")
    seed_id = seed_obj.get("id")

    # Get similar artists from Last.fm
    lfm_result = _lfm_similar(seed_name, limit=limit)
    similar = lfm_result.get("similar", []) if isinstance(lfm_result, dict) else []

    if not similar:
        return {"seed": {"id": seed_id, "name": seed_name}, "artists": [], "reason": "No similar artists found on Last.fm"}

    # Get tags
    tags_result = _lfm_tags(seed_name) if _lfm_tags else {}
    seed_tags = [t.get("name") for t in tags_result.get("tags", [])[:5]]

    result_artists = []
    for item in similar[:limit]:
        name = item.get("name", "")
        match = float(item.get("match", 0))
        spotify_id = None
        spotify_pop = 0
        try:
            sres = search().query(name, types=["artist"], limit=1)
            sitems = (sres.get("artists") or {}).get("items") or []
            if sitems:
                spotify_id = sitems[0].get("id")
                spotify_pop = sitems[0].get("popularity", 0)
        except Exception:
            pass
        result_artists.append({
            "name": name,
            "match": match,
            "spotify_id": spotify_id,
            "spotify_popularity": spotify_pop,
        })

    return {"seed": {"id": seed_id, "name": seed_name, "tags": seed_tags}, "artists": result_artists}


def discover_similar_tracks(seed_track: str | None = None, limit: int = 20) -> dict:
    """Find similar tracks using Last.fm API.

    Args:
        seed_track: Track name, or None for currently playing
        limit: Max tracks to return

    Returns:
        {"seed": {...}, "tracks": [...]}
    """
    if not LASTFM_ENABLED:
        return {"seed": None, "tracks": [], "reason": "LASTFM is disabled (set LASTFM_ENABLED=true)"}
    if not _lfm_similar:
        return {"seed": None, "tracks": [], "reason": "LASTFM_API_KEY not configured"}

    # Resolve seed track
    seed_track_obj = None
    if seed_track:
        if seed_track.startswith("spotify:track:"):
            tid = seed_track.split(":")[-1]
            try:
                seed_track_obj = tracks().get(tid)
            except Exception:
                pass
        if not seed_track_obj:
            res = search().query(seed_track, types=["track"], limit=1)
            items = (res.get("tracks") or {}).get("items") or []
            if items:
                seed_track_obj = items[0]
    else:
        current = player().get_currently_playing()
        if current:
            seed_track_obj = current.get("item")

    if not seed_track_obj:
        return {"seed": None, "tracks": [], "reason": "Seed track not found."}

    seed_name = seed_track_obj.get("name")
    seed_artists = seed_track_obj.get("artists") or []
    seed_artist_name = (seed_artists[0].get("name") if seed_artists else "")

    # Get similar tracks from Last.fm
    try:
        from . import lastfm as _lastfm_mod
        sim_func = _lastfm_mod.get_similar_tracks
    except Exception:
        try:
            from lastfm import get_similar_tracks as sim_func
        except Exception:
            return {"seed": None, "tracks": [], "reason": "Last.fm track similarity not available"}

    sim_result = sim_func(seed_artist_name, seed_name, limit=limit)
    similar = sim_result.get("similar", []) if isinstance(sim_result, dict) else []

    if not similar:
        return {"seed": {"name": seed_name, "artist": seed_artist_name}, "tracks": [], "reason": "No similar tracks found on Last.fm"}

    result_tracks = []
    for item in similar[:limit]:
        name = item.get("name", "")
        artist_name = item.get("artist", "")
        match = float(item.get("match", 0))
        spotify_id = None
        spotify_uri = None
        spotify_pop = 0
        try:
            sres = search().query(f"{artist_name} {name}", types=["track"], limit=3)
            sitems = (sres.get("tracks") or {}).get("items") or []
            for s in sitems:
                s_artists = s.get("artists") or []
                s_artist_name = (s_artists[0].get("name") if s_artists else "").lower()
                if s_artist_name == artist_name.lower() or artist_name.lower() in s_artist_name:
                    spotify_id = s.get("id")
                    spotify_uri = s.get("uri")
                    spotify_pop = s.get("popularity", 0)
                    break
        except Exception:
            pass
        result_tracks.append({
            "name": name,
            "artist": artist_name,
            "match": match,
            "spotify_id": spotify_id,
            "spotify_uri": spotify_uri,
            "spotify_popularity": spotify_pop,
        })

    return {"seed": {"name": seed_name, "artist": seed_artist_name}, "tracks": result_tracks}


def discover_similar_genres(genre: str, limit: int = 20) -> dict:
    """Find artists by genre/tag using Last.fm.

    Args:
        genre: Genre/tag name (e.g., "math rock", "jazz", "post-punk")
        limit: Max artists to return

    Returns:
        {"genre": "...", "artists": [...]}
    """
    if not LASTFM_ENABLED:
        return {"genre": genre, "artists": [], "reason": "LASTFM is disabled (set LASTFM_ENABLED=true)"}
    try:
        from . import lastfm as _lastfm_mod
    except Exception:
        try:
            from lastfm import search_by_tag as _search_by_tag
        except Exception:
            return {"genre": genre, "artists": [], "reason": "LASTFM_API_KEY not configured"}

    artists = _search_by_tag(genre, limit=limit)
    return {"genre": genre, "artists": artists}


def get_history_genres(limit: int = 10) -> dict:
    """Get aggregated genre tags from your play history.

    Requires:
    - MEMORY_ENABLED=true in .env
    - LASTFM_ENABLED=true and LASTFM_API_KEY configured (for auto-enrichment)

    Returns:
        {"genres": [{"tag": "indie rock", "count": 15}, ...]}
    """
    try:
        mem = load_memory()
        genres = get_all_genres(mem, limit=limit)
        return {"genres": genres}
    except Exception as e:
        return {"genres": [], "error": str(e)}


def discover_from_history(limit: int = 10) -> dict:
    """Discover similar artists based on your play history.

    Uses your most-played artists from memory + Last.fm similarity.

    Requires:
    - MEMORY_ENABLED=true in .env
    - LASTFM_ENABLED=true and LASTFM_API_KEY configured

    Returns:
        {"seed": {"top_artists": [...]}, "suggested": [...]}
    """
    if not LASTFM_ENABLED:
        return {"suggested": [], "reason": "LASTFM is disabled (set LASTFM_ENABLED=true)"}
    if not _lfm_similar:
        return {"suggested": [], "reason": "LASTFM_API_KEY not configured"}

    try:
        mem = load_memory()
        
        # Get most played artists from history
        artist_plays = get_history_artists(mem)
        if not artist_plays:
            return {"suggested": [], "reason": "No play history found"}
        
        # Take top artists by play count
        top_artists = [a["artist"] for a in artist_plays[:5]]
        
        # For each top artist, get similar from Last.fm
        all_similar = []
        seen = set()
        
        for artist_name in top_artists:
            try:
                result = _lfm_similar(artist_name, limit=5)
                similar = result.get("similar", []) if isinstance(result, dict) else []
                for s in similar:
                    name = s.get("name")
                    if name and name not in seen:
                        seen.add(name)
                        # Try to find in Spotify
                        spotify_id = None
                        try:
                            sres = search().query(name, types=["artist"], limit=1)
                            sitems = (sres.get("artists") or {}).get("items") or []
                            if sitems:
                                spotify_id = sitems[0].get("id")
                        except Exception:
                            pass
                        all_similar.append({
                            "name": name,
                            "match": s.get("match"),
                            "based_on": artist_name,
                            "spotify_id": spotify_id,
                        })
            except Exception:
                continue
        
        # Sort by match score
        all_similar.sort(key=lambda x: float(x.get("match", 0)), reverse=True)
        
        return {
            "seed": {"top_artists": top_artists},
            "suggested": all_similar[:limit],
        }
    except Exception as e:
        return {"suggested": [], "error": str(e)}
