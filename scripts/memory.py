"""Simple local play-history memory for SpotiClaw.

Current model (v2):
- `tracks`: one aggregated record per track_uri
- no duplicate per-play rows
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_PATH = Path.home() / ".spoticlaw" / "music_memory.json"

# Feature flag: memory is disabled by default. Set to true to enable.
MEMORY_ENABLED = os.environ.get("MEMORY_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Optional path override for memory file.
# Example: MEMORY_FILE_PATH=~/.spoticlaw/music_memory.json
_MEMORY_FILE_PATH = os.environ.get("MEMORY_FILE_PATH", "").strip()
MEMORY_PATH = Path(_MEMORY_FILE_PATH).expanduser() if _MEMORY_FILE_PATH else DEFAULT_MEMORY_PATH


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_memory() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "version": "2.0-track-aggregate",
        "profile": {
            "created_at": now,
            "updated_at": now,
        },
        "tracks": {},
    }


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_memory(memory: dict[str, Any], path: Path = MEMORY_PATH) -> None:
    _ensure_parent(path)
    profile = memory.setdefault("profile", {})
    profile["updated_at"] = utc_now_iso()
    with path.open("w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _norm_rating(value: Any) -> int | None:
    if value is None:
        return None
    try:
        v = int(value)
    except Exception:
        return None
    return v if 1 <= v <= 10 else None


def _normalize_memory_shape(data: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    created_at = profile.get("created_at") or now
    updated_at = profile.get("updated_at") or now

    tracks: dict[str, dict[str, Any]] = {}

    # Accept existing v2 format
    existing_tracks = data.get("tracks")
    if isinstance(existing_tracks, dict):
        for track_uri, t in existing_tracks.items():
            if not isinstance(t, dict) or not track_uri:
                continue
            mood_tags = t.get("mood_tags")
            if not isinstance(mood_tags, list):
                mood_tags = []
            lastfm_tags = t.get("lastfm_tags")
            if not isinstance(lastfm_tags, list):
                lastfm_tags = []
            similar_artists = t.get("similar_artists")
            if not isinstance(similar_artists, list):
                similar_artists = []

            tracks[str(track_uri)] = {
                "track_uri": str(track_uri),
                "artist_uri": t.get("artist_uri") or "",
                "album_uri": t.get("album_uri") or "",
                "track_name": t.get("track_name") or "",
                "artist_name": t.get("artist_name") or "",
                "album_name": t.get("album_name") or "",
                "first_played_at": t.get("first_played_at") or now,
                "last_played_at": t.get("last_played_at") or now,
                "play_count": int(t.get("play_count") or 0),
                "skip_count": int(t.get("skip_count") or 0),
                "user_rating": _norm_rating(t.get("user_rating")),
                "mood_tags": [str(x) for x in mood_tags if x],
                "last_source": t.get("last_source") or "unknown",
                "lastfm_tags": [str(x) for x in lastfm_tags if x],
                "similar_artists": [str(x) for x in similar_artists if x],
            }

    # Fold old v1 plays list into aggregated tracks
    existing_plays = data.get("plays")
    if isinstance(existing_plays, list):
        for p in existing_plays:
            if not isinstance(p, dict):
                continue
            track_uri = p.get("track_uri")
            if not track_uri:
                continue
            ts = p.get("ts") or now
            rec = tracks.get(track_uri)
            if rec is None:
                rec = {
                    "track_uri": track_uri,
                    "artist_uri": p.get("artist_uri") or "",
                    "album_uri": p.get("album_uri") or "",
                    "track_name": p.get("track_name") or "",
                    "artist_name": p.get("artist_name") or "",
                    "album_name": p.get("album_name") or "",
                    "first_played_at": ts,
                    "last_played_at": ts,
                    "play_count": 0,
                    "skip_count": 0,
                    "user_rating": _norm_rating(p.get("user_rating")),
                    "mood_tags": [str(x) for x in (p.get("mood_tags") or []) if x],
                    "last_source": p.get("source") or "unknown",
                    "lastfm_tags": [str(x) for x in (p.get("lastfm_tags") or []) if x],
                    "similar_artists": [str(x) for x in (p.get("similar_artists") or []) if x],
                }
                tracks[track_uri] = rec

            rec["play_count"] = int(rec.get("play_count", 0)) + 1
            if _parse_ts(ts) < _parse_ts(rec["first_played_at"]):
                rec["first_played_at"] = ts
            if _parse_ts(ts) >= _parse_ts(rec["last_played_at"]):
                rec["last_played_at"] = ts
                rec["last_source"] = p.get("source") or rec.get("last_source") or "unknown"
                for key in ("artist_uri", "album_uri", "track_name", "artist_name", "album_name"):
                    if p.get(key):
                        rec[key] = p.get(key)

    return {
        "version": "2.0-track-aggregate",
        "profile": {
            "created_at": created_at,
            "updated_at": updated_at,
        },
        "tracks": tracks,
    }


def load_memory(path: Path = MEMORY_PATH) -> dict[str, Any]:
    try:
        if not path.exists():
            mem = default_memory()
            save_memory(mem, path)
            return mem

        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            raise ValueError("invalid root")

        normalized = _normalize_memory_shape(raw)

        # Persist normalized shape if legacy/mismatched
        if raw.get("version") != normalized.get("version") or set(raw.keys()) != {"version", "profile", "tracks"}:
            save_memory(normalized, path)

        return normalized
    except Exception:
        mem = default_memory()
        save_memory(mem, path)
        return mem


def record_play(
    memory: dict[str, Any],
    *,
    track_uri: str,
    artist_uri: str | None = None,
    album_uri: str | None = None,
    track_name: str | None = None,
    artist_name: str | None = None,
    album_name: str | None = None,
    source: str = "unknown",
    user_rating: int | None = None,
    mood_tags: list[str] | None = None,
) -> None:
    if not MEMORY_ENABLED or not track_uri:
        return

    now = utc_now_iso()
    tracks = memory.setdefault("tracks", {})
    if not isinstance(tracks, dict):
        memory["tracks"] = {}
        tracks = memory["tracks"]

    rec = tracks.get(track_uri)
    if not isinstance(rec, dict):
        rec = {
            "track_uri": track_uri,
            "artist_uri": artist_uri or "",
            "album_uri": album_uri or "",
            "track_name": track_name or "",
            "artist_name": artist_name or "",
            "album_name": album_name or "",
            "first_played_at": now,
            "last_played_at": now,
            "play_count": 0,
            "skip_count": 0,
            "user_rating": None,
            "mood_tags": [],
            "last_source": source,
            "lastfm_tags": [],
            "similar_artists": [],
        }
        tracks[track_uri] = rec

    rec["play_count"] = int(rec.get("play_count") or 0) + 1
    if not rec.get("first_played_at"):
        rec["first_played_at"] = now
    rec["last_played_at"] = now
    rec["last_source"] = source or rec.get("last_source") or "unknown"

    for k, v in {
        "artist_uri": artist_uri,
        "album_uri": album_uri,
        "track_name": track_name,
        "artist_name": artist_name,
        "album_name": album_name,
    }.items():
        if v:
            rec[k] = v

    rating = _norm_rating(user_rating)
    if rating is not None:
        rec["user_rating"] = rating

    if mood_tags:
        old = rec.get("mood_tags") if isinstance(rec.get("mood_tags"), list) else []
        merged = list(dict.fromkeys([*(str(x) for x in old if x), *(str(x) for x in mood_tags if x)]))
        rec["mood_tags"] = merged


def set_track_feedback(
    memory: dict[str, Any],
    *,
    track_uri: str,
    user_rating: int | None = None,
    mood_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    tracks = memory.get("tracks")
    if not isinstance(tracks, dict):
        return None
    rec = tracks.get(track_uri)
    if not isinstance(rec, dict):
        return None

    rating = _norm_rating(user_rating)
    if user_rating is not None and rating is not None:
        rec["user_rating"] = rating

    if mood_tags is not None:
        rec["mood_tags"] = list(dict.fromkeys([str(x) for x in mood_tags if x]))

    rec["last_played_at"] = rec.get("last_played_at") or utc_now_iso()
    return rec


def get_recent_plays(memory: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    tracks = memory.get("tracks")
    if not isinstance(tracks, dict):
        return []
    items = [v for v in tracks.values() if isinstance(v, dict)]
    items.sort(key=lambda x: _parse_ts(x.get("last_played_at") or ""), reverse=True)
    return items[: max(0, limit)]


def enrich_play_entry(
    entry: dict[str, Any],
    lastfm_tags: list[str] | None = None,
    similar_artists: list[str] | None = None,
) -> dict[str, Any]:
    """Add Last.fm enrichment data to a track entry."""
    if not entry:
        return entry
    entry = dict(entry)
    if lastfm_tags:
        entry["lastfm_tags"] = list(dict.fromkeys([str(x) for x in lastfm_tags if x]))
    if similar_artists:
        entry["similar_artists"] = list(dict.fromkeys([str(x) for x in similar_artists if x]))
    return entry


def get_all_genres(memory: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    """Get aggregated genre tags from track memory."""
    from collections import Counter

    tags: list[str] = []
    tracks = memory.get("tracks")
    if not isinstance(tracks, dict):
        return []

    for t in tracks.values():
        if not isinstance(t, dict):
            continue
        lt = t.get("lastfm_tags")
        if isinstance(lt, list):
            tags.extend([str(x) for x in lt if x])

    if not tags:
        return []

    counts = Counter(tags)
    return [{"tag": t, "count": c} for t, c in counts.most_common(limit)]


def get_history_artists(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Get artists with weighted play counts from aggregated track memory."""
    from collections import Counter

    counts: Counter[str] = Counter()
    tracks = memory.get("tracks")
    if not isinstance(tracks, dict):
        return []

    for t in tracks.values():
        if not isinstance(t, dict):
            continue
        artist = t.get("artist_name")
        if not artist:
            continue
        counts[str(artist)] += int(t.get("play_count") or 1)

    return [{"artist": a, "count": c} for a, c in counts.most_common()]