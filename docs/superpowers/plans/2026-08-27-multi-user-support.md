# Multi-User Support (Trusted-Group Profiles) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let multiple people share one self-hosted instance via a lightweight, password-free profile picker, with conversations private per profile while settings/credentials/personas stay shared.

**Architecture:** A new `Profile` entity (`backend/profiles.py`, JSON-file store) identifies "who's asking." Conversations gain an optional `profile_id` field; every conversation-scoped endpoint accepts an **optional** `X-Profile-Id` header — present means scoped/private, absent means unscoped (today's behavior, required for the separate `the_ai_counsel_mcp` package and `/api/ask` to keep working unmodified). The frontend gates on a picker (`ProfileGate` → `ProfilePicker`), stores the chosen profile id in `localStorage`, and `api.js` attaches the header automatically on every conversation-related request.

**Tech Stack:** FastAPI + Pydantic (backend), React (frontend), flat JSON file storage (matches existing `backend/personas.py`/`backend/storage.py` conventions) — no new dependencies.

## Global Constraints

- No password/PIN for profiles (v1) — picking a profile is not a security boundary.
- Settings, credentials (LLM API keys), and personas remain fully shared — never scoped by profile.
- `X-Profile-Id` is **optional** on every conversation endpoint. Missing header = unscoped, unchanged from pre-feature behavior. This is required for `the_ai_counsel_mcp` and `/api/ask` compatibility — do not make it required anywhere.
- Profile creation is self-service (no admin gate). Profile deletion is self-service and self-scoped only (a profile can delete only itself).
- `docs/superpowers/` is gitignored in this repo despite one earlier tracked spec/plan pair — commit files under it with `git add -f`.

---

### Task 1: Backend — Profile model and CRUD store

**Files:**
- Create: `backend/profiles.py`
- Test: `backend/tests/test_profiles.py`

**Interfaces:**
- Produces: `Profile` (Pydantic model: `id: str, name: str, avatar_emoji: str, color: str, created_at: str`), `get_all_profiles() -> List[Profile]`, `get_profile(profile_id: str) -> Optional[Profile]`, `create_profile(name: str, avatar_emoji: Optional[str] = None) -> Profile`, `delete_profile(profile_id: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for backend profile CRUD functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.profiles as profiles_module
from backend.profiles import (
    Profile,
    create_profile,
    delete_profile,
    get_all_profiles,
    get_profile,
)


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the profiles file to a temp path and reset the in-memory cache."""
    profiles_file = tmp_path / "profiles.json"
    monkeypatch.setattr(profiles_module, "_PROFILES_FILE", profiles_file)
    monkeypatch.setattr(profiles_module, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(profiles_module, "_profiles_cache", None)
    yield
    monkeypatch.setattr(profiles_module, "_profiles_cache", None)


def test_get_all_profiles_empty_by_default():
    assert get_all_profiles() == []


def test_create_profile_returns_profile_instance():
    created = create_profile("Sarah")
    assert isinstance(created, Profile)
    assert created.name == "Sarah"
    assert created.id == "sarah"


def test_create_profile_defaults_avatar_emoji():
    created = create_profile("Sarah")
    assert created.avatar_emoji == profiles_module.DEFAULT_AVATAR_EMOJI


def test_create_profile_accepts_custom_avatar_emoji():
    created = create_profile("Sarah", avatar_emoji="🐙")
    assert created.avatar_emoji == "🐙"


def test_create_profile_slugifies_name_with_punctuation():
    created = create_profile("O'Brien!")
    assert created.id == "o-brien"


def test_create_profile_dedupes_id_collisions():
    first = create_profile("Sarah")
    second = create_profile("Sarah")
    assert first.id != second.id
    assert second.id == "sarah-2"


def test_create_profile_persists_to_disk():
    created = create_profile("Sarah")
    profiles_file = profiles_module._PROFILES_FILE
    assert profiles_file.exists()
    data = json.loads(profiles_file.read_text(encoding="utf-8"))
    assert data[0]["id"] == created.id
    assert data[0]["name"] == "Sarah"


def test_get_all_profiles_returns_created_profiles():
    create_profile("Sarah")
    create_profile("Tom")
    result = get_all_profiles()
    assert {p.name for p in result} == {"Sarah", "Tom"}


def test_get_profile_returns_none_for_unknown_id():
    assert get_profile("ghost") is None


def test_get_profile_returns_matching_profile():
    created = create_profile("Sarah")
    fetched = get_profile(created.id)
    assert fetched is not None
    assert fetched.id == created.id


def test_delete_profile_removes_it():
    created = create_profile("Sarah")
    assert delete_profile(created.id) is True
    assert get_profile(created.id) is None
    assert get_all_profiles() == []


def test_delete_profile_unknown_id_returns_false():
    assert delete_profile("ghost") is False


def test_delete_profile_only_removes_target():
    first = create_profile("Sarah")
    second = create_profile("Tom")
    delete_profile(first.id)
    remaining = get_all_profiles()
    assert len(remaining) == 1
    assert remaining[0].id == second.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_profiles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.profiles'`

- [ ] **Step 3: Write the implementation**

```python
"""User profile registry for multi-user support (trusted-group model).

Profiles identify "who's asking" for conversation privacy only — they carry
no password/PIN and are not a security boundary. See
docs/superpowers/specs/2026-08-27-multi-user-support-design.md.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

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


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "profile"


def _unique_id(name: str, existing_ids: set) -> str:
    base_slug = _slugify(name)
    candidate = base_slug
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate


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
    profile_id = _unique_id(name, existing_ids)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_profiles.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/profiles.py backend/tests/test_profiles.py
git commit -m "feat: add Profile model and CRUD store for multi-user support"
```

---

### Task 2: Backend — conversation storage gains optional profile scoping

**Files:**
- Modify: `backend/storage.py` (`_build_index_entry` ~line 249, `create_conversation` ~line 331, `get_conversation` ~line 363, `list_conversations` ~line 406, `delete_conversation` ~line 585; add two new functions)
- Test: `backend/tests/test_conversation_profiles.py` (new file — keeps `test_storage_modes.py` focused on its existing mode-inference concern)

**Interfaces:**
- Consumes: nothing from Task 1 (storage.py stores a raw `profile_id: Optional[str]` string; it never imports `backend.profiles`).
- Produces: `create_conversation(conversation_id, mode="council", profile_id=None)`, `get_conversation(conversation_id, profile_id=None)`, `list_conversations(profile_id=None)`, `delete_conversation(conversation_id, profile_id=None)` — in every case, `profile_id=None` means **unscoped** (matches current/pre-feature behavior exactly). Also `get_unclaimed_conversation_count() -> int` and `claim_unclaimed_conversations(profile_id: str) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for optional profile_id scoping on conversation storage."""

from backend import storage


def test_create_conversation_without_profile_id_is_unclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    conversation = storage.create_conversation("conv-1")
    assert conversation["profile_id"] is None


def test_create_conversation_stamps_profile_id(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    conversation = storage.create_conversation("conv-1", profile_id="sarah")
    assert conversation["profile_id"] == "sarah"


def test_get_conversation_unscoped_returns_regardless_of_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    # No profile_id passed -> unscoped, matches pre-feature/MCP behavior
    assert storage.get_conversation("conv-1") is not None


def test_get_conversation_scoped_returns_none_for_wrong_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    assert storage.get_conversation("conv-1", profile_id="tom") is None


def test_get_conversation_scoped_returns_conversation_for_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    result = storage.get_conversation("conv-1", profile_id="sarah")
    assert result is not None
    assert result["id"] == "conv-1"


def test_list_conversations_unscoped_returns_all(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    storage.create_conversation("conv-2", profile_id="tom")
    storage.create_conversation("conv-3")
    assert len(storage.list_conversations()) == 3


def test_list_conversations_scoped_filters_by_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    storage.create_conversation("conv-2", profile_id="tom")
    result = storage.list_conversations(profile_id="sarah")
    assert len(result) == 1
    assert result[0]["id"] == "conv-1"


def test_delete_conversation_scoped_refuses_wrong_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    assert storage.delete_conversation("conv-1", profile_id="tom") is False
    assert storage.get_conversation("conv-1") is not None


def test_delete_conversation_scoped_allows_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    assert storage.delete_conversation("conv-1", profile_id="sarah") is True
    assert storage.get_conversation("conv-1") is None


def test_delete_conversation_unscoped_deletes_regardless_of_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    assert storage.delete_conversation("conv-1") is True
    assert storage.get_conversation("conv-1") is None


def test_unclaimed_count_counts_conversations_with_no_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1")
    storage.create_conversation("conv-2", profile_id="sarah")
    storage.create_conversation("conv-3")
    assert storage.get_unclaimed_conversation_count() == 2


def test_claim_unclaimed_conversations_assigns_profile_id(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1")
    storage.create_conversation("conv-2", profile_id="tom")
    claimed = storage.claim_unclaimed_conversations("sarah")
    assert claimed == 1
    assert storage.get_conversation("conv-1", profile_id="sarah") is not None
    assert storage.get_conversation("conv-2", profile_id="tom") is not None


def test_claim_unclaimed_conversations_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1")
    storage.claim_unclaimed_conversations("sarah")
    second_pass = storage.claim_unclaimed_conversations("tom")
    assert second_pass == 0
    assert storage.get_conversation("conv-1", profile_id="sarah") is not None


def test_claim_unclaimed_conversations_no_op_when_none_unclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.create_conversation("conv-1", profile_id="sarah")
    assert storage.claim_unclaimed_conversations("tom") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_conversation_profiles.py -v`
Expected: FAIL — `create_conversation() got an unexpected keyword argument 'profile_id'` (and similar for the other functions/`AttributeError` for the two new functions)

- [ ] **Step 3: Implement the storage changes**

In `backend/storage.py`, update `_build_index_entry` (around line 249) to include `profile_id`:

```python
def _build_index_entry(
    conversation: Dict[str, Any],
    *,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    maybe_repair_conversation_title(conversation)
    entry = {
        "id": conversation["id"],
        "created_at": conversation["created_at"],
        "title": conversation.get("title", DEFAULT_CONVERSATION_TITLE),
        "mode": mode if mode is not None else infer_conversation_mode(conversation),
        "message_count": len(conversation["messages"]),
        "profile_id": conversation.get("profile_id"),
    }
    run_summary = derive_run_summary(conversation)
    if run_summary:
        entry["run_summary"] = run_summary
    cost = derive_conversation_cost(conversation)
    if cost:
        entry["total_cost"] = cost["total_cost"]
        entry["cost_status"] = cost["cost_status"]
        entry["total_calls"] = cost["total_calls"]
    return entry
```

Replace `create_conversation` (around line 331):

```python
def create_conversation(
    conversation_id: str,
    mode: str = "council",
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation
        mode: Conversation mode — "council" or "advisors"
        profile_id: Owning profile, or None for unclaimed (matches
            pre-multi-user behavior; used by /api/ask and the MCP server)

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": "New Conversation",
        "mode": _normalize_conversation_mode(mode),
        "profile_id": profile_id,
        "messages": []
    }

    # Save to file
    path = get_conversation_path(conversation_id)
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)

    # Update index
    _update_index_entry(conversation, mode=conversation["mode"])

    return conversation
```

Replace `get_conversation` (around line 363):

```python
def get_conversation(
    conversation_id: str,
    profile_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation
        profile_id: If given, only return the conversation when it belongs
            to this profile (None otherwise). If omitted, unscoped — returns
            the conversation regardless of owner (pre-multi-user behavior;
            used by /api/ask and the MCP server).

    Returns:
        Conversation dict or None if not found (or not owned by profile_id)
    """
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return None

    with open(path, 'r') as f:
        conversation = json.load(f)

    if profile_id is not None and conversation.get("profile_id") != profile_id:
        return None

    if maybe_repair_conversation_title(conversation):
        # Save to persist the repaired title
        save_conversation(conversation)
    conversation["mode"] = infer_conversation_mode(conversation)
    return conversation
```

Replace `list_conversations` (around line 406):

```python
def list_conversations(profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).
    Uses cached index file for O(1) performance.

    Args:
        profile_id: If given, only conversations owned by this profile are
            returned. If omitted, unscoped — returns every conversation
            (pre-multi-user behavior; used by /api/ask and the MCP server).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    index = _load_index()

    if index is None:
        index = rebuild_index()

    if profile_id is None:
        return index

    return [entry for entry in index if entry.get("profile_id") == profile_id]
```

Replace `delete_conversation` (around line 585):

```python
def delete_conversation(
    conversation_id: str,
    profile_id: Optional[str] = None,
) -> bool:
    """
    Delete a conversation.

    Args:
        conversation_id: Conversation identifier
        profile_id: If given, only delete when owned by this profile. If
            omitted, unscoped — deletes regardless of owner (pre-multi-user
            behavior; used by /api/ask and the MCP server).

    Returns:
        True if deleted, False if not found (or not owned by profile_id)
    """
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return False

    if profile_id is not None:
        with open(path, 'r') as f:
            existing = json.load(f)
        if existing.get("profile_id") != profile_id:
            return False

    os.remove(path)

    # Update index
    _remove_from_index(conversation_id)

    return True
```

Add two new functions at the end of the file:

```python
def get_unclaimed_conversation_count() -> int:
    """Count conversations with no owning profile (pre-existing or created via /api/ask/MCP)."""
    ensure_data_dir()
    index = _load_index()
    if index is None:
        index = rebuild_index()
    return sum(1 for entry in index if not entry.get("profile_id"))


def claim_unclaimed_conversations(profile_id: str) -> int:
    """Attach every currently-unclaimed conversation to profile_id. Idempotent.

    Returns the number of conversations claimed by this call.
    """
    ensure_data_dir()
    index = _load_index()
    if index is None:
        index = rebuild_index()

    claimed = 0
    for entry in index:
        if entry.get("profile_id"):
            continue
        conversation = get_conversation(entry["id"])
        if conversation is None:
            continue
        conversation["profile_id"] = profile_id
        save_conversation(conversation)
        claimed += 1
    return claimed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_conversation_profiles.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run the full existing storage test suite to confirm no regression**

Run: `uv run pytest backend/tests/test_storage_modes.py backend/tests/test_conversation_title.py backend/tests/test_conversation_cost.py backend/tests/test_run_summary.py -v`
Expected: all PASS (these call `create_conversation`/`get_conversation`/etc. with no `profile_id` argument — the new parameter is optional with a default, so this must not break them)

- [ ] **Step 6: Commit**

```bash
git add backend/storage.py backend/tests/test_conversation_profiles.py
git commit -m "feat: add optional profile_id scoping to conversation storage"
```

---

### Task 3: Backend — wire profiles into the API

**Files:**
- Modify: `backend/main.py`
  - Import line ~6 (add `Header` to the fastapi import), and near line 61 (add `from .profiles import get_all_profiles, get_profile, create_profile, delete_profile` right after the existing multi-line `.personas` import)
  - `AskRequest` (~line 395): add `profile_id` field
  - New dependency function (place near `_require_admin`, ~line 313)
  - New route group (place between `POST /api/conversations` at line ~669 and `GET /api/conversations/{conversation_id}` at line ~677 — the unclaimed-summary route MUST be registered before the `{conversation_id}` route or FastAPI will match `unclaimed-summary` as a `conversation_id` path parameter instead)
  - Updated: `list_conversations` (663), `create_conversation` (669), `get_conversation` (677), `delete_conversation` (686), `get_conversation_progress` (695), `send_message_stream` (738), `send_debate_message_stream` (965), `start_debate_stream` (1271), `send_message_sync` (1405), `ask_oneshot` (1467)
  - New routes: `GET /api/profiles`, `POST /api/profiles`, `DELETE /api/profiles/{profile_id}`, `POST /api/profiles/{profile_id}/claim-unclaimed`
- Test: `backend/tests/test_profile_endpoints.py`

**Interfaces:**
- Consumes: `Profile`, `get_all_profiles`, `get_profile`, `create_profile`, `delete_profile` (Task 1); `storage.create_conversation/get_conversation/list_conversations/delete_conversation/get_unclaimed_conversation_count/claim_unclaimed_conversations` (Task 2).
- Produces: `get_active_profile_id(x_profile_id: Optional[str] = Header(None)) -> Optional[str]` FastAPI dependency, reusable by any future conversation-scoped endpoint.

- [ ] **Step 1: Write the failing tests**

```python
"""Endpoint-level tests for profile-scoped conversation access."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend import storage
    from backend import profiles as profiles_module
    from backend.main import app

    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(profiles_module, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(profiles_module, "_PROFILES_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr(profiles_module, "_profiles_cache", None)

    with TestClient(app) as c:
        yield c


def test_list_profiles_starts_empty(client):
    response = client.get("/api/profiles")
    assert response.status_code == 200
    assert response.json() == []


def test_create_profile_returns_profile(client):
    response = client.post("/api/profiles", json={"name": "Sarah"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Sarah"
    assert body["id"] == "sarah"


def test_create_profile_rejects_blank_name(client):
    response = client.post("/api/profiles", json={"name": "   "})
    assert response.status_code == 400


def test_delete_profile_requires_matching_header(client):
    created = client.post("/api/profiles", json={"name": "Sarah"}).json()
    response = client.delete(f"/api/profiles/{created['id']}", headers={"X-Profile-Id": "someone-else"})
    assert response.status_code == 403


def test_delete_profile_succeeds_for_self(client):
    created = client.post("/api/profiles", json={"name": "Sarah"}).json()
    response = client.delete(f"/api/profiles/{created['id']}", headers={"X-Profile-Id": created["id"]})
    assert response.status_code == 200
    assert client.get("/api/profiles").json() == []


def test_conversations_are_unscoped_without_header(client):
    sarah = client.post("/api/profiles", json={"name": "Sarah"}).json()
    tom = client.post("/api/profiles", json={"name": "Tom"}).json()
    client.post("/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": sarah["id"]})
    client.post("/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": tom["id"]})

    response = client.get("/api/conversations")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_conversations_are_scoped_with_header(client):
    sarah = client.post("/api/profiles", json={"name": "Sarah"}).json()
    tom = client.post("/api/profiles", json={"name": "Tom"}).json()
    client.post("/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": sarah["id"]})
    client.post("/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": tom["id"]})

    response = client.get("/api/conversations", headers={"X-Profile-Id": sarah["id"]})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_conversation_scoped_to_other_profile_is_404(client):
    sarah = client.post("/api/profiles", json={"name": "Sarah"}).json()
    tom = client.post("/api/profiles", json={"name": "Tom"}).json()
    created = client.post(
        "/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": sarah["id"]}
    ).json()

    response = client.get(f"/api/conversations/{created['id']}", headers={"X-Profile-Id": tom["id"]})
    assert response.status_code == 404


def test_unknown_profile_header_is_rejected(client):
    response = client.get("/api/conversations", headers={"X-Profile-Id": "ghost"})
    assert response.status_code == 400


def test_unclaimed_summary_and_claim_flow(client):
    # Created with no header at all -> unclaimed
    client.post("/api/conversations", json={"mode": "council"})
    sarah = client.post("/api/profiles", json={"name": "Sarah"}).json()

    summary = client.get("/api/conversations/unclaimed-summary")
    assert summary.status_code == 200
    assert summary.json()["count"] == 1

    claim = client.post(f"/api/profiles/{sarah['id']}/claim-unclaimed")
    assert claim.status_code == 200
    assert claim.json()["claimed"] == 1

    assert client.get("/api/conversations/unclaimed-summary").json()["count"] == 0
    scoped = client.get("/api/conversations", headers={"X-Profile-Id": sarah["id"]})
    assert len(scoped.json()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_profile_endpoints.py -v`
Expected: FAIL — `404 Not Found` for `/api/profiles` (route doesn't exist yet), etc.

- [ ] **Step 3: Implement the API wiring**

In `backend/main.py`, update the fastapi import line:

```python
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
```

Add the profiles import right after the existing multi-line `.personas` import block (which ends around line 61 with a closing `)`):

```python
from .personas import (
    get_all_personas,
    save_persona_override,
    delete_persona_override,
    get_persona,
    create_persona,
    update_custom_persona,
    delete_persona,
)
from .profiles import get_all_profiles, get_profile, create_profile, delete_profile
```

Add the dependency function near `_require_admin` (around line 313):

```python
def get_active_profile_id(x_profile_id: Optional[str] = Header(None)) -> Optional[str]:
    """Optional caller identity for conversation-scoped endpoints.

    Absent header => unscoped, identical to pre-multi-user behavior. This
    is required for the_ai_counsel_mcp and any direct API/script caller,
    which have no concept of a profile and must keep working unmodified.
    Present header must reference a real profile.
    """
    if x_profile_id and not get_profile(x_profile_id):
        raise HTTPException(status_code=400, detail="Unknown profile")
    return x_profile_id
```

Add `profile_id: Optional[str] = None` to `AskRequest` (around line 395):

```python
class AskRequest(BaseModel):
    content: str
    models: Optional[List[str]] = None
    chairman_model: Optional[str] = None
    web_search: bool = False
    execution_mode: ExecutionMode = "chat_only"
    documents: Optional[List[Dict[str, Any]]] = None
    profile_id: Optional[str] = None
```

Replace the conversation CRUD endpoints (lines 663-692), inserting the new profile routes and the unclaimed-summary route **before** the `{conversation_id}` GET route:

```python
@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(profile_id: Optional[str] = Depends(get_active_profile_id)):
    """List all conversations (metadata only). Scoped to profile_id when the caller sends one."""
    return storage.list_conversations(profile_id)


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id, mode=request.mode, profile_id=profile_id)
    return conversation


class ProfileCreateRequest(BaseModel):
    name: str
    avatar_emoji: Optional[str] = None


@app.get("/api/profiles")
async def list_profiles():
    """List all profiles. No auth — this is how the picker discovers who can be chosen."""
    return [p.model_dump() for p in get_all_profiles()]


@app.post("/api/profiles")
async def add_profile(body: ProfileCreateRequest):
    """Create a new profile. Self-service — no gate on who can create one."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    created = create_profile(body.name.strip(), body.avatar_emoji)
    return created.model_dump()


@app.delete("/api/profiles/{profile_id}")
async def remove_profile(profile_id: str, x_profile_id: Optional[str] = Header(None)):
    """Delete a profile and its private conversations. A profile can only delete itself."""
    if x_profile_id != profile_id:
        raise HTTPException(status_code=403, detail="Can only delete your own profile")
    if not get_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    for entry in storage.list_conversations(profile_id):
        storage.delete_conversation(entry["id"], profile_id)
    delete_profile(profile_id)
    return {"deleted": profile_id}


@app.get("/api/conversations/unclaimed-summary")
async def unclaimed_conversations_summary():
    """Count of conversations with no owning profile, for the picker's import prompt."""
    return {"count": storage.get_unclaimed_conversation_count()}


@app.post("/api/profiles/{profile_id}/claim-unclaimed")
async def claim_unclaimed(profile_id: str):
    """Attach every currently-unclaimed conversation to profile_id. Idempotent."""
    if not get_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    claimed = storage.claim_unclaimed_conversations(profile_id)
    return {"claimed": claimed}


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id, profile_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Delete a conversation."""
    deleted = storage.delete_conversation(conversation_id, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


@app.get("/api/conversations/{conversation_id}/progress")
async def get_conversation_progress(
    conversation_id: str,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Return live progress for an active streaming run, or {active: false} if none."""
    if profile_id is not None and storage.get_conversation(conversation_id, profile_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    run = _active_runs.get(conversation_id)
```

(The rest of `get_conversation_progress`'s body — everything from `if run is None:` onward — is unchanged; only the signature and the new ownership-check line above it change.)

For the three message/debate streaming endpoints and the sync message endpoint, apply the same mechanical substitution — add the dependency parameter and pass it through to `storage.get_conversation`:

`send_message_stream` (line 738-743):
```python
@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Send a message and stream the 3-stage council process."""
    conversation = storage.get_conversation(conversation_id, profile_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
```

`send_debate_message_stream` (line 965-970):
```python
@app.post("/api/conversations/{conversation_id}/message/debate")
async def send_debate_message_stream(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Send a message and stream the multi-round iterative debate process."""
    conversation = storage.get_conversation(conversation_id, profile_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
```

`start_debate_stream` (line 1271-1276):
```python
@app.post("/api/conversations/{conversation_id}/debate/stream")
async def start_debate_stream(
    conversation_id: str,
    body: StartDebateRequest,
    request: Request,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Start an advisor debate and stream results via SSE."""
    conversation = storage.get_conversation(conversation_id, profile_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
```

`send_message_sync` (line 1405-1410):
```python
@app.post("/api/conversations/{conversation_id}/message")
async def send_message_sync(
    conversation_id: str,
    body: SendMessageRequest,
    profile_id: Optional[str] = Depends(get_active_profile_id),
):
    """Send a message and return JSON response (non-streaming)."""
    conversation = storage.get_conversation(conversation_id, profile_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
```

In `ask_oneshot` (line 1467-1503), pass `profile_id` through to conversation creation:

```python
@app.post("/api/ask")
async def ask_oneshot(body: AskRequest):
    """Run a one-shot query, persist it as a conversation, and return JSON."""
    settings = get_settings()
    models = body.models if body.models else settings.council_models
    # ... (unchanged preflight/search/document logic above `conversation_id = str(uuid.uuid4())`)

    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id, profile_id=body.profile_id)
    conversation["title"] = storage.derive_conversation_title(body.content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_profile_endpoints.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run the full backend test suite to confirm no regression**

Run: `uv run pytest`
Expected: all tests PASS (excluding any pre-existing unrelated Windows-only failures already known in this repo — see prior sessions' `test_credentials_store.py`/`test_documents.py` PDF temp-file issues, unrelated to this change)

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_profile_endpoints.py
git commit -m "feat: wire profile-scoped access into conversation API endpoints"
```

---

### Task 4: Frontend — active-profile session helper and API header injection

**Files:**
- Create: `frontend/src/profileSession.js`
- Modify: `frontend/src/api.js` (import + 9 conversation call sites + 5 new profile-related methods)

**Interfaces:**
- Produces: `getActiveProfileId()`, `setActiveProfileId(profileId)`, `clearActiveProfileId()` (all synchronous, `localStorage`-backed); `api.getProfiles()`, `api.createProfile(name, avatarEmoji)`, `api.deleteProfile(profileId)`, `api.getUnclaimedConversationsSummary()`, `api.claimUnclaimedConversations(profileId)`.
- Consumes: nothing from earlier tasks (pure frontend, talks to the endpoints Task 3 added).

There is no frontend test runner configured in this project (`frontend/package.json` only has `lint`/`build`/`dev`/`preview` scripts) — verification for this task is `npm run lint` plus the manual check in Step 3.

- [ ] **Step 1: Create the session helper**

```javascript
// frontend/src/profileSession.js
const ACTIVE_PROFILE_KEY = 'ai-counsel:active-profile-id';

export function getActiveProfileId() {
  try {
    return localStorage.getItem(ACTIVE_PROFILE_KEY);
  } catch {
    return null;
  }
}

export function setActiveProfileId(profileId) {
  try {
    localStorage.setItem(ACTIVE_PROFILE_KEY, profileId);
  } catch {
    // localStorage unavailable (e.g. private browsing) - profile just won't
    // persist across reloads; ProfileGate will show the picker again.
  }
}

export function clearActiveProfileId() {
  try {
    localStorage.removeItem(ACTIVE_PROFILE_KEY);
  } catch {
    // no-op
  }
}
```

- [ ] **Step 2: Update `frontend/src/api.js`**

Add the import and a small header helper near the top of the file (after the existing `getApiBase`/`API_BASE` block, before `export const api = {`):

```javascript
import { getActiveProfileId } from './profileSession';

function _profileHeaders() {
  const profileId = getActiveProfileId();
  return profileId ? { 'X-Profile-Id': profileId } : {};
}
```

Update the 9 conversation call sites to attach `_profileHeaders()`:

```javascript
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      headers: _profileHeaders(),
    });
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  async createConversation(options = {}) {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ..._profileHeaders(),
      },
      body: JSON.stringify(options),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      { headers: _profileHeaders() }
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  async getConversationProgress(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/progress`,
      { headers: _profileHeaders() }
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation progress');
    }
    return response.json();
  },

  async deleteConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      { method: 'DELETE', headers: _profileHeaders() }
    );
    if (!response.ok) {
      throw new Error('Failed to delete conversation');
    }
    return response.json();
  },

  async sendMessage(conversationId, content, webSearch = false) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ..._profileHeaders(),
        },
        body: JSON.stringify({ content, web_search: webSearch }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },
```

For the three streaming methods — `sendDebateStream` (line ~447, hits `/debate/stream`), `sendMessageStream` (line ~493, hits `/message/stream`), and `streamDebateMessage` (line ~540, hits `/message/debate`) — add `..._profileHeaders()` into each one's existing `headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' }` object, e.g.:

```javascript
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/debate/stream?_t=${Date.now()}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-cache',
          ..._profileHeaders(),
        },
        body: JSON.stringify(body),
        signal,
        cache: 'no-store',
      }
    );
```

Apply the identical `..._profileHeaders()` addition to the `message/stream` and `message/debate` fetch calls' headers objects.

Add the five new profile methods (place after `deleteConversation`, before the `getSettings` method):

```javascript
  /**
   * List all profiles for the picker.
   */
  async getProfiles() {
    const response = await fetch(`${API_BASE}/api/profiles`);
    if (!response.ok) {
      throw new Error('Failed to list profiles');
    }
    return response.json();
  },

  /**
   * Create a new profile.
   */
  async createProfile(name, avatarEmoji) {
    const response = await fetch(`${API_BASE}/api/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, avatar_emoji: avatarEmoji || null }),
    });
    if (!response.ok) {
      throw new Error('Failed to create profile');
    }
    return response.json();
  },

  /**
   * Delete a profile (can only delete your own — send its own id as the active profile).
   */
  async deleteProfile(profileId) {
    const response = await fetch(`${API_BASE}/api/profiles/${profileId}`, {
      method: 'DELETE',
      headers: _profileHeaders(),
    });
    if (!response.ok) {
      throw new Error('Failed to delete profile');
    }
    return response.json();
  },

  /**
   * Count of conversations with no owning profile (pre-upgrade or created via /api/ask/MCP).
   */
  async getUnclaimedConversationsSummary() {
    const response = await fetch(`${API_BASE}/api/conversations/unclaimed-summary`);
    if (!response.ok) {
      throw new Error('Failed to get unclaimed conversation summary');
    }
    return response.json();
  },

  /**
   * Attach every currently-unclaimed conversation to profileId. Idempotent.
   */
  async claimUnclaimedConversations(profileId) {
    const response = await fetch(`${API_BASE}/api/profiles/${profileId}/claim-unclaimed`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to claim unclaimed conversations');
    }
    return response.json();
  },
```

- [ ] **Step 3: Manual verification**

Run: `cd frontend && npm run lint`
Expected: no new errors introduced by this task's changes (pre-existing unrelated errors in other files may still be present — see prior session notes on lint being advisory-only in CI).

Run: `cd frontend && npm run dev`, open the dev server URL, open browser DevTools → Console, and run:
```javascript
fetch('http://localhost:8001/api/profiles').then(r => r.json()).then(console.log)
```
Expected: `[]` (empty array — no profiles created yet), confirming the backend route from Task 3 is reachable from the frontend's dev origin.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/profileSession.js frontend/src/api.js
git commit -m "feat: add profile session helper and wire X-Profile-Id into api.js"
```

---

### Task 5: Frontend — ProfilePicker component

**Files:**
- Create: `frontend/src/components/ProfilePicker.jsx`
- Create: `frontend/src/components/ProfilePicker.css`

**Interfaces:**
- Consumes: `api.getProfiles`, `api.createProfile`, `api.claimUnclaimedConversations`, `api.getUnclaimedConversationsSummary` (Task 4).
- Produces: `<ProfilePicker onProfileChosen={(profile) => void} />` — `profile` is the full `{id, name, avatar_emoji, color, created_at}` object from the API.

- [ ] **Step 1: Create the component**

```jsx
import { useEffect, useState } from 'react';
import { api } from '../api';
import './ProfilePicker.css';

export default function ProfilePicker({ onProfileChosen }) {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [unclaimedCount, setUnclaimedCount] = useState(0);
  const [addingProfile, setAddingProfile] = useState(false);
  const [newName, setNewName] = useState('');
  const [newEmoji, setNewEmoji] = useState('');
  const [importExisting, setImportExisting] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getProfiles(), api.getUnclaimedConversationsSummary()])
      .then(([profileList, summary]) => {
        if (cancelled) return;
        setProfiles(profileList);
        setUnclaimedCount(summary.count || 0);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const finishChoosing = async (profile) => {
    if (unclaimedCount > 0 && importExisting) {
      try {
        await api.claimUnclaimedConversations(profile.id);
      } catch (err) {
        console.error('Failed to import existing conversations:', err);
      }
    }
    onProfileChosen(profile);
  };

  const handleCreateProfile = async () => {
    if (!newName.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.createProfile(newName.trim(), newEmoji.trim() || null);
      await finishChoosing(created);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="profile-picker profile-picker--loading">Loading profiles…</div>;
  }

  return (
    <div className="profile-picker">
      <h1 className="profile-picker__title">Who's using The AI Counsel?</h1>

      <div className="profile-picker__grid">
        {profiles.map((profile) => (
          <button
            key={profile.id}
            type="button"
            className="profile-picker__card"
            style={{ '--profile-color': profile.color }}
            onClick={() => finishChoosing(profile)}
          >
            <span className="profile-picker__emoji">{profile.avatar_emoji}</span>
            <span className="profile-picker__name">{profile.name}</span>
          </button>
        ))}

        {addingProfile ? (
          <div className="profile-picker__card profile-picker__card--form">
            <input
              type="text"
              className="profile-picker__input"
              placeholder="Name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              maxLength={40}
              autoFocus
            />
            <input
              type="text"
              className="profile-picker__input profile-picker__input--emoji"
              placeholder="🙂"
              value={newEmoji}
              onChange={(e) => setNewEmoji(e.target.value)}
              maxLength={4}
            />
            <button
              type="button"
              className="profile-picker__save-btn"
              onClick={handleCreateProfile}
              disabled={saving || !newName.trim()}
            >
              {saving ? 'Creating…' : 'Create'}
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="profile-picker__card profile-picker__card--add"
            onClick={() => setAddingProfile(true)}
          >
            <span className="profile-picker__add-icon">＋</span>
            <span className="profile-picker__name">Add Profile</span>
          </button>
        )}
      </div>

      {unclaimedCount > 0 && (
        <label className="profile-picker__import-row">
          <input
            type="checkbox"
            checked={importExisting}
            onChange={(e) => setImportExisting(e.target.checked)}
          />
          <span>
            Import {unclaimedCount} existing conversation{unclaimedCount === 1 ? '' : 's'} into
            whichever profile I pick or create next
          </span>
        </label>
      )}

      {error && <p className="profile-picker__error">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Create the stylesheet**

```css
/* ProfilePicker — Netflix/Plex-style profile selection gate */

.profile-picker {
  width: 100%;
  max-width: 720px;
  margin: 10vh auto 0;
  padding: 0 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 32px;
  font-family: var(--font-ui);
}

.profile-picker--loading {
  color: var(--text-secondary);
  font-size: calc(15px * var(--font-scale));
}

.profile-picker__title {
  font-family: var(--font-display);
  font-size: calc(28px * var(--font-scale));
  font-weight: 700;
  color: var(--text-primary);
  text-align: center;
  margin: 0;
}

.profile-picker__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 20px;
  width: 100%;
}

.profile-picker__card {
  background: var(--bg-card);
  border: 1.5px solid var(--border-glass);
  border-radius: 16px;
  padding: 24px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  color: inherit;
  font-family: inherit;
  transition: border-color 0.2s ease, transform 0.15s ease, background 0.2s ease;
}

.profile-picker__card:hover {
  border-color: var(--profile-color, rgba(168, 85, 247, 0.5));
  transform: translateY(-2px);
  background: rgba(255, 255, 255, 0.05);
}

.profile-picker__card--add {
  border-style: dashed;
  color: var(--text-secondary);
}

.profile-picker__card--form {
  cursor: default;
  gap: 8px;
}

.profile-picker__emoji {
  font-size: calc(36px * var(--font-scale));
  line-height: 1;
}

.profile-picker__add-icon {
  font-size: calc(28px * var(--font-scale));
  color: #c084fc;
}

.profile-picker__name {
  font-size: calc(14px * var(--font-scale));
  font-weight: 600;
  color: var(--text-primary);
}

.profile-picker__input {
  width: 100%;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-glass);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: calc(13px * var(--font-scale));
  padding: 6px 8px;
  box-sizing: border-box;
  text-align: center;
}

.profile-picker__input--emoji {
  font-size: calc(16px * var(--font-scale));
}

.profile-picker__save-btn {
  width: 100%;
  background: rgba(168, 85, 247, 0.2);
  border: 1px solid rgba(168, 85, 247, 0.4);
  border-radius: 8px;
  color: #c084fc;
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
  padding: 6px 0;
  cursor: pointer;
}

.profile-picker__save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.profile-picker__import-row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: calc(13px * var(--font-scale));
  cursor: pointer;
}

.profile-picker__import-row input {
  accent-color: #a855f7;
}

.profile-picker__error {
  color: #fca5a5;
  font-size: calc(13px * var(--font-scale));
}
```

- [ ] **Step 3: Manual verification**

Run: `cd frontend && npm run lint`
Expected: no new errors in `ProfilePicker.jsx`.

Since `ProfilePicker` isn't mounted anywhere yet (that's Task 6), this component can't be manually exercised in the browser until Task 6 wires it in — full manual verification happens there.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ProfilePicker.jsx frontend/src/components/ProfilePicker.css
git commit -m "feat: add ProfilePicker component"
```

---

### Task 6: Frontend — gate the app behind the picker, wire switch/delete into Sidebar

**Files:**
- Create: `frontend/src/components/ProfileGate.jsx`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/src/App.jsx` (function signature ~line 126; add `handleDeleteProfile` near other handlers; `<Sidebar>` call site ~lines 1634-1648)
- Modify: `frontend/src/components/Sidebar.jsx` (props list, JSX, new local state)
- Modify: `frontend/src/components/Sidebar.css` (new `.sidebar-profile*` rules)

**Interfaces:**
- Consumes: `ProfilePicker` (Task 5); `getActiveProfileId`, `setActiveProfileId`, `clearActiveProfileId` (Task 4); `api.getProfiles`, `api.deleteProfile` (Task 4).
- Produces: `App` now accepts `{ activeProfile, onSwitchProfile }` props (both required at the call site in `main.jsx`).

- [ ] **Step 1: Create `ProfileGate.jsx`**

```jsx
import { useEffect, useState } from 'react';
import { api } from '../api';
import { getActiveProfileId, setActiveProfileId, clearActiveProfileId } from '../profileSession';
import ProfilePicker from './ProfilePicker';

export default function ProfileGate({ children }) {
  const [activeProfile, setActiveProfile] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const storedId = getActiveProfileId();
    if (!storedId) {
      setChecking(false);
      return undefined;
    }
    api.getProfiles()
      .then((profiles) => {
        if (cancelled) return;
        const match = profiles.find((p) => p.id === storedId);
        if (match) {
          setActiveProfile(match);
        } else {
          clearActiveProfileId();
        }
      })
      .catch(() => {
        // Backend unreachable at startup - fall through to the picker
        // rather than hang; picking again is harmless once it's back.
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => { cancelled = true; };
  }, []);

  const handleProfileChosen = (profile) => {
    setActiveProfileId(profile.id);
    setActiveProfile(profile);
  };

  const handleSwitchProfile = () => {
    clearActiveProfileId();
    window.location.reload();
  };

  if (checking) {
    return null;
  }

  if (!activeProfile) {
    return <ProfilePicker onProfileChosen={handleProfileChosen} />;
  }

  return children(activeProfile, handleSwitchProfile);
}
```

- [ ] **Step 2: Wire it into `main.jsx`**

```jsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ProfileGate from './components/ProfileGate.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ProfileGate>
      {(activeProfile, onSwitchProfile) => (
        <App activeProfile={activeProfile} onSwitchProfile={onSwitchProfile} />
      )}
    </ProfileGate>
  </StrictMode>,
)
```

- [ ] **Step 3: Accept the new props in `App.jsx`**

Change the function signature (line 126):

```javascript
function App({ activeProfile, onSwitchProfile }) {
```

Add an import for `clearActiveProfileId` alongside the existing `api` import near the top of the file:

```javascript
import { clearActiveProfileId } from './profileSession';
```

Add a `handleDeleteProfile` handler near the other handler definitions (place it near `handleAbort` or another top-level handler — exact neighboring code isn't load-bearing, just keep it a sibling function inside `App`):

```javascript
  const handleDeleteProfile = async () => {
    try {
      await api.deleteProfile(activeProfile.id);
    } finally {
      clearActiveProfileId();
      window.location.reload();
    }
  };
```

Update the `<Sidebar>` call site (around line 1634) to pass the three new props:

```jsx
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleMobileSelectConversation}
        onNewConversation={handleMobileNewConversation}
        onNewAdvisors={handleMobileNewAdvisors}
        onDeleteConversation={handleDeleteConversation}
        onOpenSettings={handleMobileOpenSettings}
        isLoading={isLoading}
        onAbort={handleAbort}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onGoHome={() => resetAppState(null)}
        dateFormat={dateFormat}
        activeProfile={activeProfile}
        onSwitchProfile={onSwitchProfile}
        onDeleteProfile={handleDeleteProfile}
      />
```

- [ ] **Step 4: Add the profile indicator to `Sidebar.jsx`**

Add three new props to the function signature and a `confirmingProfileDelete` state:

```javascript
export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onNewAdvisors,
  onDeleteConversation,
  onOpenSettings,
  isLoading,
  onAbort,
  isOpen,
  onClose,
  onGoHome,
  dateFormat = 'auto',
  activeProfile,
  onSwitchProfile,
  onDeleteProfile,
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(null);
  const [confirmingProfileDelete, setConfirmingProfileDelete] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
```

Add a handler alongside the existing `handleDeleteClick`/`handleConfirmDelete`:

```javascript
  const handleProfileDeleteConfirm = () => {
    setConfirmingProfileDelete(false);
    onDeleteProfile();
  };
```

Insert a new block right after the existing `sidebar-header` div (after its closing `</div>` at the line containing `⚙️` button's closing tags, before the `{/* Mode Actions */}` comment):

```jsx
      {activeProfile && (
        <div className="sidebar-profile">
          <span className="sidebar-profile__emoji">{activeProfile.avatar_emoji}</span>
          <span className="sidebar-profile__name">{activeProfile.name}</span>
          <button
            type="button"
            className="sidebar-profile__switch-btn"
            onClick={onSwitchProfile}
            title="Switch profile"
          >
            Switch
          </button>
          {confirmingProfileDelete ? (
            <span className="sidebar-profile__delete-confirm">
              Delete profile and {conversations.length} conversation{conversations.length === 1 ? '' : 's'}?
              <button type="button" onClick={handleProfileDeleteConfirm} title="Confirm">✓</button>
              <button type="button" onClick={() => setConfirmingProfileDelete(false)} title="Cancel">✕</button>
            </span>
          ) : (
            <button
              type="button"
              className="sidebar-profile__delete-btn"
              onClick={() => setConfirmingProfileDelete(true)}
              title="Delete profile"
            >
              🗑️
            </button>
          )}
        </div>
      )}

```

- [ ] **Step 5: Add the CSS**

Append to `frontend/src/components/Sidebar.css`:

```css
/* ── Profile Indicator ── */
.sidebar-profile {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 13px;
}

.sidebar-profile__emoji {
  font-size: 16px;
  line-height: 1;
}

.sidebar-profile__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.sidebar-profile__switch-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
  flex-shrink: 0;
}

.sidebar-profile__switch-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.sidebar-profile__delete-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  opacity: 0.6;
  flex-shrink: 0;
}

.sidebar-profile__delete-btn:hover {
  opacity: 1;
}

.sidebar-profile__delete-confirm {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #fca5a5;
  flex-shrink: 0;
}

.sidebar-profile__delete-confirm button {
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  font-size: 13px;
}
```

- [ ] **Step 6: Manual verification**

Run: `cd frontend && npm run lint`
Expected: no new errors in `ProfileGate.jsx`, `App.jsx`, `Sidebar.jsx`, `main.jsx`.

Start both servers (`uv run python -m backend.main` and `cd frontend && npm run dev`), open the dev URL in a browser, then walk through:
1. First load shows the profile picker (no profiles exist yet) with only a dashed "+ Add Profile" tile.
2. Type a name, click Create — the picker disappears and the normal landing page appears; the sidebar shows the new profile's emoji/name with a "Switch" button.
3. Start a council or advisor conversation; it appears in the sidebar's conversation list.
4. Open DevTools → Application → Local Storage, confirm `ai-counsel:active-profile-id` is set to the created profile's id.
5. Click "Switch" in the sidebar — the page reloads and the picker reappears, now showing the existing profile as a card alongside "+ Add Profile."
6. Click the existing profile's card — you're returned to the landing page and the same conversation from step 3 is still in the sidebar.
7. Open a second browser (or an incognito window) and repeat steps 1-3 with a different profile name — confirm its conversation list does NOT show the first profile's conversation from step 3.
8. Back in the first profile, click the sidebar's 🗑️ next to the profile name, confirm the count shown matches the number of conversations created, confirm deletion — the picker reappears and that profile is gone from the grid.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ProfileGate.jsx frontend/src/main.jsx frontend/src/App.jsx frontend/src/components/Sidebar.jsx frontend/src/components/Sidebar.css
git commit -m "feat: gate the app behind a profile picker, add switch/delete controls"
```

---

### Task 7: Documentation sync

**Files:**
- Modify: `README.md` (Additional Features bullet list, ~line 254)
- Modify: `CHANGELOG.md` (`[Unreleased]` section, ~line 8)

Per `docs/DOC-SYNC.md`, `docs/mcp/TOOLS.md` and `docs/mcp/EXAMPLES.md` do **not** need updates for this feature: the MCP server's `model_chat`/`quick_ask`-style tools call `/api/ask` unscoped (no `profile_id` passed through), by design, matching "MCP keeps working exactly as today" — there is no new MCP-facing parameter to document.

- [ ] **Step 1: Add the README feature bullet**

In `README.md`, insert a new bullet into the "Additional Features" list (near the other access/deployment-related bullets, right before the Docker Deployment bullet):

```markdown
- **Multi-User Profiles** — Pick or add a lightweight named profile (no password) to keep your conversation history private from others sharing the same instance; settings, personas, and API keys stay shared across everyone
- **Docker Deployment** — Single-container production deployment via `docker compose`
```

- [ ] **Step 2: Add the CHANGELOG entry**

In `CHANGELOG.md`, fill in the empty `## [Unreleased]` section:

```markdown
## [Unreleased]

### Added
- Multi-user profiles: a lightweight, password-free picker lets multiple people share one instance while keeping conversation history private per person. Settings, personas, and API keys remain shared across all profiles.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document multi-user profile support"
```
