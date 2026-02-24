"""Simple local play-history memory for SpotiClaw."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_PATH = Path.home() / ".spoticlaw" / "music_memory.json"

# Feature flag: set to "false" to disable memory logging
MEMORY_ENABLED = os.environ.get("MEMORY_ENABLED", "true").lower() != "false"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_memory() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "version": "1.0-simple-log",
        "profile": {
            "created_at": now,
            "updated_at": now,
        },
        "plays": [],
    }


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_memory(memory: dict[str, Any], path: Path = DEFAULT_MEMORY_PATH) -> None:
    _ensure_parent(path)
    profile = memory.setdefault("profile", {})
    profile["updated_at"] = utc_now_iso()
    with path.open("w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def _normalize_memory_shape(data: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    created_at = profile.get("created_at") or now
    updated_at = profile.get("updated_at") or now

    plays: list[dict[str, Any]] = []

    existing_plays = data.get("plays")
    if isinstance(existing_plays, list):
        for p in existing_plays:
            if isinstance(p, dict) and p.get("track_uri"):
                plays.append(
                    {
                        "ts": p.get("ts") or now,
                        "source": p.get("source") or "unknown",
                        "track_uri": p.get("track_uri") or "",
                        "artist_uri": p.get("artist_uri") or "",
                        "album_uri": p.get("album_uri") or "",
                        "track_name": p.get("track_name") or "",
                        "artist_name": p.get("artist_name") or "",
                        "album_name": p.get("album_name") or "",
                    }
                )

    if not plays:
        history = data.get("history") if isinstance(data.get("history"), dict) else {}
        last_track = history.get("last_played_track") if isinstance(history.get("last_played_track"), dict) else {}
        for track_uri, ts in last_track.items():
            if not track_uri:
                continue
            plays.append(
                {
                    "ts": ts or now,
                    "source": "legacy-migrated",
                    "track_uri": str(track_uri),
                    "artist_uri": "",
                    "album_uri": "",
                    "track_name": "",
                    "artist_name": "",
                    "album_name": "",
                }
            )

    return {
        "version": "1.0-simple-log",
        "profile": {
            "created_at": created_at,
            "updated_at": updated_at,
        },
        "plays": plays,
    }


def load_memory(path: Path = DEFAULT_MEMORY_PATH) -> dict[str, Any]:
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

        if raw.get("version") != normalized.get("version") or set(raw.keys()) != {"version", "profile", "plays"}:
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
) -> None:
    if not MEMORY_ENABLED or not track_uri:
        return

    plays = memory.setdefault("plays", [])
    if not isinstance(plays, list):
        memory["plays"] = []
        plays = memory["plays"]

    plays.append(
        {
            "ts": utc_now_iso(),
            "source": source,
            "track_uri": track_uri,
            "artist_uri": artist_uri or "",
            "album_uri": album_uri or "",
            "track_name": track_name or "",
            "artist_name": artist_name or "",
            "album_name": album_name or "",
        }
    )


def get_recent_plays(memory: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    plays = memory.get("plays", [])
    if not isinstance(plays, list):
        return []
    return plays[-max(0, limit):]


def enrich_play_entry(
    entry: dict[str, Any],
    lastfm_tags: list[str] | None = None,
    similar_artists: list[str] | None = None,
) -> dict[str, Any]:
    """Add Last.fm enrichment data to a play entry."""
    if not entry:
        return entry
    entry = dict(entry)
    if lastfm_tags:
        entry["lastfm_tags"] = lastfm_tags
    if similar_artists:
        entry["similar_artists"] = similar_artists
    return entry


def get_all_genres(memory: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    """Get aggregated genre tags from play history.
    
    Returns list of {tag, count} sorted by count descending.
    """
    from collections import Counter
    tags: list[str] = []
    plays = memory.get("plays", [])
    if not isinstance(plays, list):
        return []
    
    for p in plays:
        lt = p.get("lastfm_tags")
        if isinstance(lt, list):
            tags.extend(lt)
    
    if not tags:
        return []
    
    counts = Counter(tags)
    return [{"tag": t, "count": c} for t, c in counts.most_common(limit)]


def get_history_artists(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Get unique artists from play history with play counts."""
    from collections import Counter
    artists: list[str] = []
    plays = memory.get("plays", [])
    if not isinstance(plays, list):
        return []
    
    for p in plays:
        an = p.get("artist_name")
        if an:
            artists.append(an)
    
    if not artists:
        return []
    
    counts = Counter(artists)
    return [{"artist": a, "count": c} for a, c in counts.most_common()]
