"""Shared slug/id generation for user-created entities (personas, profiles).

A single, small, dependency-free helper so every "create a named thing and
give it a stable id" feature doesn't reinvent slugification independently.
"""

import re
from typing import Iterable


def slugify(name: str, *, fallback: str) -> str:
    """Lowercase, hyphenate, and strip a name down to a URL/id-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or fallback


def unique_slug(name: str, existing_ids: Iterable[str], *, fallback: str) -> str:
    """Slugify name, then suffix with -2, -3, ... until it doesn't collide."""
    base_slug = slugify(name, fallback=fallback)
    existing = set(existing_ids)
    candidate = base_slug
    suffix = 2
    while candidate in existing:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate
