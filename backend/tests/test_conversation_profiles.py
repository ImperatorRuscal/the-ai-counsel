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
