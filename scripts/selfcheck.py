#!/usr/bin/env python3
"""SpotiClaw lightweight self-check (no extra dependencies).

Usage:
    python scripts/selfcheck.py

What it checks:
1) Local imports for key modules
2) Python syntax compilation of scripts/
3) Optional runtime smoke calls when auth env/cache exist
"""

from __future__ import annotations

import compileall
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _ok(msg: str) -> None:
    print(f"✅ {msg}")


def _warn(msg: str) -> None:
    print(f"⚠️  {msg}")


def _fail(msg: str) -> None:
    print(f"❌ {msg}")


def main() -> int:
    sys.path.insert(0, str(SCRIPTS))

    # 1) Import checks
    try:
        importlib.import_module("spoticlaw")
        importlib.import_module("memory")
        importlib.import_module("lastfm")
        _ok("Module imports succeeded (spoticlaw, memory, lastfm)")
    except Exception as exc:  # pragma: no cover
        _fail(f"Import check failed: {exc}")
        return 1

    # 2) Syntax/compile checks
    compiled = compileall.compile_dir(str(SCRIPTS), quiet=1)
    if not compiled:
        _fail("Compilation check failed in scripts/")
        return 1
    _ok("Compilation check passed for scripts/")

    # 3) Optional authenticated smoke checks
    needed_env = ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI"]
    has_env = all(os.getenv(k) for k in needed_env)
    has_cache = (ROOT / ".spotify_cache").exists()

    if has_env and has_cache:
        try:
            import spoticlaw  # type: ignore

            me = spoticlaw.user().me()
            if isinstance(me, dict) and me.get("id"):
                _ok(f"Authenticated API smoke OK (user={me.get('id')})")
            else:
                _warn("Authenticated smoke returned unexpected profile payload")
        except Exception as exc:  # pragma: no cover
            _warn(f"Authenticated smoke failed (non-blocking): {exc}")
    else:
        _warn("Skipped authenticated smoke (missing env vars or .spotify_cache)")

    print("\nSelf-check finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
