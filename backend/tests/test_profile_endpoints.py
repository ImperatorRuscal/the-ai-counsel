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


def test_ask_oneshot_rejects_unknown_profile_id(client):
    response = client.post(
        "/api/ask",
        json={"content": "hello", "profile_id": "ghost"},
    )
    assert response.status_code == 400


def test_send_message_scoped_to_other_profile_is_404(client):
    sarah = client.post("/api/profiles", json={"name": "Sarah"}).json()
    tom = client.post("/api/profiles", json={"name": "Tom"}).json()
    created = client.post(
        "/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": sarah["id"]}
    ).json()

    response = client.post(
        f"/api/conversations/{created['id']}/message",
        json={"content": "hello"},
        headers={"X-Profile-Id": tom["id"]},
    )
    assert response.status_code == 404


def test_delete_profile_cascades_to_its_conversations(client):
    sarah = client.post("/api/profiles", json={"name": "Sarah"}).json()
    created = client.post(
        "/api/conversations", json={"mode": "council"}, headers={"X-Profile-Id": sarah["id"]}
    ).json()

    response = client.delete(f"/api/profiles/{sarah['id']}", headers={"X-Profile-Id": sarah["id"]})
    assert response.status_code == 200

    assert client.get(f"/api/conversations/{created['id']}").status_code == 404
    assert client.get("/api/conversations").json() == []
