"""User profile registry for multi-user support (trusted-group model).

Profiles identify "who's asking" for conversation privacy only — they carry
no password/PIN and are not a security boundary. See
docs/superpowers/specs/2026-08-27-multi-user-support-design.md.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .slugify import unique_slug

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_PROFILES_FILE = _DATA_DIR / "profiles.json"

DEFAULT_AVATAR_EMOJI = "🙂"

_PROFILE_COLORS = [
    "#ef4444", "#f59e0b", "#8b5cf6", "#6366f1", "#10b981",
    "#3b82f6", "#ec4899", "#f97316", "#06b6d4", "#64748b",
    "#eab308", "#14b8a6",
]


class Profile(BaseModel):
    """A named identity used to keep conversations private per person."""
    id: str
    name: str
    avatar_emoji: str
    color: str
    created_at: str


_profiles_cache: Optional[List[Dict[str, Any]]] = None


def _load_profiles() -> List[Dict[str, Any]]:
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache
    if not _PROFILES_FILE.exists():
        _profiles_cache = []
        return _profiles_cache
    try:
        _profiles_cache = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(
            "Failed to parse %s; starting with an empty profile list. "
            "If a profile is created or deleted before this is fixed, "
            "the corrupted file will be overwritten and its contents lost.",
            _PROFILES_FILE,
            exc_info=True,
        )
        _profiles_cache = []
    return _profiles_cache


def _save_profiles(profiles: List[Dict[str, Any]]) -> None:
    global _profiles_cache
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(profiles, indent=2, ensure_ascii=False))
        os.replace(tmp_path, _PROFILES_FILE)
    except Exception:
        os.unlink(tmp_path)
        raise
    _profiles_cache = profiles


def get_all_profiles() -> List[Profile]:
    return [Profile(**p) for p in _load_profiles()]


def get_profile(profile_id: str) -> Optional[Profile]:
    for record in _load_profiles():
        if record["id"] == profile_id:
            return Profile(**record)
    return None


def create_profile(name: str, avatar_emoji: Optional[str] = None) -> Profile:
    profiles = _load_profiles()
    existing_ids = {p["id"] for p in profiles}
    profile_id = unique_slug(name, existing_ids, fallback="profile")
    color = _PROFILE_COLORS[len(profiles) % len(_PROFILE_COLORS)]
    record = {
        "id": profile_id,
        "name": name,
        "avatar_emoji": avatar_emoji or DEFAULT_AVATAR_EMOJI,
        "color": color,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    profiles.append(record)
    _save_profiles(profiles)
    return Profile(**record)


def delete_profile(profile_id: str) -> bool:
    profiles = _load_profiles()
    remaining = [p for p in profiles if p["id"] != profile_id]
    if len(remaining) == len(profiles):
        return False
    _save_profiles(remaining)
    return True
