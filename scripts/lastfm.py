"""Last.fm API client for music discovery and similarity.

Provides:
- artist.getSimilar: find similar artists (non-deprecated)
- artist.getTopTags: get genre tags for an artist
- track.getSimilar: find similar tracks
- track.getTopTags: get genre tags for a track

Usage:
    from spoticlaw import lastfm
    similar = lastfm.get_similar_artists("Modest Mouse", limit=10)
    tags = lastfm.get_artist_tags("Portishead")
"""

from __future__ import annotations

import os
import hashlib
import time
from typing import Any

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "http://ws.audioscrobbler.com/2.0/"

# Load API key from environment
API_KEY = os.environ.get("LASTFM_API_KEY") or os.environ.get("SPOTIFY_LASTFM_API_KEY")


def _api_sig(params: dict[str, str], secret: str) -> str:
    """Generate Last.fm API signature (for authenticated calls)."""
    # Most calls only need API key, but some need auth
    # We'll implement when needed
    return ""


def _get(
    method: str,
    auto_camel: bool = True,
    **params: Any,
) -> dict[str, Any]:
    """Make a Last.fm API call."""
    if not API_KEY:
        return {"error": "LASTFM_API_KEY not set"}

    params["method"] = method
    params["api_key"] = API_KEY
    params["format"] = "json"

    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e)}

    # Handle Last.fm error responses
    if isinstance(data, dict) and data.get("error"):
        return data

    # Auto-convert camelCase keys to snake_case for easier access
    if auto_camel and isinstance(data, dict):
        return _camel_to_snake(data)

    return data


def _camel_to_snake(d: Any) -> Any:
    """Recursively convert camelCase dict keys to snake_case."""
    if isinstance(d, dict):
        new_dict = {}
        for k, v in d.items():
            # Simple camel to snake
            snake = ""
            for i, c in enumerate(k):
                if c.isupper() and i > 0:
                    snake += "_"
                snake += c.lower()
            new_dict[snake] = _camel_to_snake(v)
        return new_dict
    elif isinstance(d, list):
        return [_camel_to_snake(item) for item in d]
    return d


def get_similar_artists(
    artist: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Get similar artists to the given artist.

    This is the core non-deprecated similarity endpoint!

    Returns:
        {
            "artist": "Modest Mouse",
            "similar": [
                {"name": "Pixies", "match": 0.95},
                {"name": "The Flaming Lips", "match": 0.88},
                ...
            ]
        }
    """
    result = _get("artist.getSimilar", artist=artist, limit=limit)
    # Last.fm returns 'similarartists' key - keep it as-is (camelCase not converted)
    sim = result.get("similarartists") or result.get("similar_artists") or {}
    if isinstance(sim, dict):
        # artist key can be a list or a single dict
        artist_data = sim.get("artist")
        if isinstance(artist_data, list):
            return {"similar": artist_data}
        elif isinstance(artist_data, dict):
            return {"similar": [artist_data]}
    return {"similar": []}


def get_artist_tags(artist: str, limit: int = 10) -> dict[str, Any]:
    """Get top tags (genres) for an artist.

    Returns:
        {
            "artist": "Portishead",
            "tags": [
                {"name": "trip-hop", "count": 100},
                {"name": "electronic", "count": 80},
                {"name": "alternative", "count": 50},
            ]
        }
    """
    result = _get("artist.getTopTags", artist=artist)
    toptags = result.get("toptags", {}).get("tag", [])
    # Limit and format
    tags = []
    for tag in toptags[:limit]:
        if isinstance(tag, dict):
            tags.append({
                "name": tag.get("name", ""),
                "count": int(tag.get("count", 0)),
            })
    return {
        "artist": artist,
        "tags": tags,
    }


def get_track_tags(artist: str, track: str, limit: int = 10) -> dict[str, Any]:
    """Get top tags for a specific track."""
    result = _get("track.getTopTags", artist=artist, track=track)
    toptags = result.get("toptags", {}).get("tag", [])
    tags = []
    for tag in toptags[:limit]:
        if isinstance(tag, dict):
            tags.append({
                "name": tag.get("name", ""),
                "count": int(tag.get("count", 0)),
            })
    return {
        "artist": artist,
        "track": track,
        "tags": tags,
    }


def get_similar_tracks(
    artist: str,
    track: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Get similar tracks to the given track."""
    result = _get("track.getSimilar", artist=artist, track=track, limit=limit)
    sim_tracks = result.get("similartracks", {}).get("track", [])
    tracks = []
    for t in sim_tracks:
        if isinstance(t, dict):
            tracks.append({
                "name": t.get("name", ""),
                "artist": (t.get("artist") or {}).get("name", ""),
                "match": float(t.get("match", 0)),
                "url": t.get("url", ""),
            })
    return {
        "artist": artist,
        "track": track,
        "similar": tracks,
    }


def search_artist(artist: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search for an artist by name."""
    result = _get("artist.search", artist=artist, limit=limit)
    matches = result.get("results", {}).get("artistmatches", {}).get("artist", [])
    artists = []
    for a in matches:
        if isinstance(a, dict):
            artists.append({
                "name": a.get("name", ""),
                "mbid": a.get("mbid", ""),
                "url": a.get("url", ""),
                "listeners": int(a.get("listeners", 0)),
            })
    return artists


# --- Convenience wrappers that combine with Spotify data ---


def enrich_artist_genres(spotify_artist_id: str, artist_name: str) -> dict[str, Any]:
    """Get artist genres from Last.fm to supplement Spotify data.

    This is useful when Spotify returns empty genres.
    """
    tags = get_artist_tags(artist_name)
    return {
        "spotify_id": spotify_artist_id,
        "name": artist_name,
        "lastfm_tags": [t["name"] for t in tags.get("tags", [])],
        "source": "lastfm",
    }


def search_by_tag(tag: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search for artists by tag (genre).

    Example: search_by_tag("post-punk", limit=10)
    Returns artists tagged with that genre in Last.fm.
    """
    result = _get("tag.getTopArtists", tag=tag, limit=limit)
    topresp = result.get("topartists", {})
    artists = topresp.get("artist", []) if isinstance(topresp, dict) else []
    
    out = []
    for a in artists:
        if isinstance(a, dict):
            out.append({
                "name": a.get("name", ""),
                "url": a.get("url", ""),
                "streamable": a.get("streamable", "0") == "1",
            })
    return out


def get_tag_info(tag: str) -> dict[str, Any]:
    """Get info about a tag (genre)."""
    result = _get("tag.getInfo", tag=tag)
    taginfo = result.get("tag", {})
    return {
        "name": taginfo.get("name", ""),
        "url": taginfo.get("url", ""),
        "reach": int(taginfo.get("reach", 0)),
        "total": int(taginfo.get("total", 0)),
        "wiki": taginfo.get("wiki", {}).get("summary", ""),
    }


def get_chart_top_tracks(limit: int = 20) -> list[dict[str, Any]]:
    """Get top tracks globally on Last.fm."""
    result = _get("chart.getTopTracks", limit=limit)
    tracks = result.get("tracks", {}).get("track", []) if isinstance(result.get("tracks"), dict) else []
    
    out = []
    for t in tracks:
        if isinstance(t, dict):
            out.append({
                "name": t.get("name", ""),
                "artist": (t.get("artist") or {}).get("name", ""),
                "url": t.get("url", ""),
                "playcount": int(t.get("playcount", 0)),
            })
    return out


def get_chart_top_artists(limit: int = 20) -> list[dict[str, Any]]:
    """Get top artists globally on Last.fm."""
    result = _get("chart.getTopArtists", limit=limit)
    artists = result.get("artists", {}).get("artist", []) if isinstance(result.get("artists"), dict) else []
    
    out = []
    for a in artists:
        if isinstance(a, dict):
            out.append({
                "name": a.get("name", ""),
                "url": a.get("url", ""),
                "playcount": int(a.get("playcount", 0)),
                "listeners": int(a.get("listeners", 0)),
            })
    return out


# Export names
__all__ = [
    "API_KEY",
    "get_similar_artists",
    "get_artist_tags",
    "get_track_tags",
    "get_similar_tracks",
    "search_artist",
    "enrich_artist_genres",
    "search_by_tag",
    "get_tag_info",
    "get_chart_top_tracks",
    "get_chart_top_artists",
]