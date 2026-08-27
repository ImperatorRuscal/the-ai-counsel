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
