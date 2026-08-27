# Multi-User Support (Trusted-Group Profiles)

## Goal

Let more than one person share a single self-hosted instance of The AI Counsel while keeping their conversation history private from each other. This targets a **trusted small group** (household, small team) — not a hardened multi-tenant SaaS. There is no password/session security boundary here, the same way the existing `LLM_COUNCIL_ADMIN_TOKEN` admin gate is a convenience/deterrent, not a hardened auth system.

## Approved behavior

- **Identification is a lightweight profile picker**, Netflix/Plex-style: on load, pick your name/avatar from a list, or add a new one. No password, no PIN (deferred; the data model doesn't preclude adding one later).
- **Profile creation is self-service** — anyone at the picker can add a new profile. There is no admin gate on this.
- **Isolation scope is conversations only.** LLM API keys/credentials, global settings (council composition, personas, prompts, advisor presets, etc.) remain fully shared across all profiles on the instance, exactly as they work today. Only conversation history is private per profile.
- **Deletion is self-service and scoped to your own profile.** From the picker (or a profile menu), a profile can delete itself. This also deletes that profile's private conversations, behind a confirmation prompt that states the conversation count.
- **Existing conversations are not auto-migrated.** Conversations created before this feature (and anything created via the one-shot `/api/ask` API or the MCP server, which never go through the picker) are "unclaimed" (`profile_id: null`). The first time this browser sees the picker, if unclaimed conversations exist, an extra "Import existing conversations" option lets whoever picks/creates a profile next claim them all into that profile. Unclaimed conversations remain reachable directly by ID through the API even if never claimed.

## Out of scope

Explicitly deferred, to keep this slice tight:

- PIN or password auth for profiles.
- Per-profile settings, model preferences, or LLM API keys (all decided as shared).
- An admin role or access control over who can create/see profiles.
- Real session/cookie-based auth, CSRF protection, or any hardened security boundary — the header-based identity below is a convenience mechanism, not a security control, consistent with the trusted-group threat model.
- Rate limiting or per-profile cost tracking/budgets (a natural future use of the existing `backend/costs.py`, but not this spec).

## Architecture

### Data model

New `Profile` model in a new `backend/profiles.py`, following the same pattern as `Persona` in `backend/personas.py` (slugified id, emoji/color card, JSON-file store with an in-memory cache):

```python
class Profile(BaseModel):
    id: str            # slug of name, e.g. "sarah"; collision-suffixed like custom personas
    name: str
    avatar_emoji: str
    color: str
    created_at: str     # ISO 8601
```

Stored as a flat list in `data/profiles.json`. Reuse the slugify + collision-suffix logic already written for custom personas (`_slugify`, `_unique_custom_id` in `backend/personas.py`) rather than duplicating it — extract it to a small shared helper both modules import.

### Conversation isolation

Add `profile_id: Optional[str] = None` to:
- Each conversation record (`data/conversations/<id>.json`).
- Each entry in `data/conversations_index.json`.

`None` means unclaimed. `backend/storage.py`'s list/get/create/delete functions gain a `profile_id` parameter:
- `list_conversations(profile_id)` — only returns entries where `entry["profile_id"] == profile_id`.
- `get_conversation(conversation_id, profile_id)` — returns `None` (→ 404 at the API layer) if the conversation exists but belongs to a different profile. Returning 404 rather than 403 avoids confirming another profile's conversation exists.
- `create_conversation(..., profile_id)` — stamps the new record with the creating profile's id.
- `delete_conversation(conversation_id, profile_id)` — same ownership check as `get_conversation` before deleting.

### Request identity

The frontend sends `X-Profile-Id: <id>` on every conversation-scoped request once a profile is active. A small FastAPI dependency in `backend/main.py`:

```python
def require_profile_id(x_profile_id: str = Header(...)) -> str:
    if not get_profile(x_profile_id):
        raise HTTPException(400, "No active profile")
    return x_profile_id
```

applied to all conversation endpoints (`/api/conversations`, `/api/conversations/{id}`, `/api/conversations/{id}/message`, `/api/conversations/{id}/debate/stream`, `/api/conversations/{id}/progress`, etc.). Settings, credentials, and persona endpoints are untouched — they never read this header, keeping the "conversations private, everything else shared" boundary enforced at the API layer, not just by convention.

This works uniformly across the app's SSE streaming endpoints because the frontend's `_consumeSSEStream` helper (`frontend/src/api.js`) already streams via `fetch()`, not native `EventSource` — so a custom header is not a blocker there.

The one-shot `/api/ask` endpoint and the MCP server accept an **optional** `profile_id` in the request body instead of the header (external callers haven't been through a picker). Omitted → unclaimed, same as legacy conversations.

### New endpoints

- `GET /api/profiles` — list all profiles. No header required; this is how the picker populates itself before any profile is active.
- `POST /api/profiles` — create `{name, avatar_emoji?}` → `Profile`. `avatar_emoji` is optional and defaults to a placeholder (matching custom-persona creation, which defaults to 🧑‍💼); color is always auto-assigned from the same palette rotation used for custom personas, not user-supplied.
- `DELETE /api/profiles/{profile_id}` — deletes the profile and cascades to delete its private conversations. Requires `X-Profile-Id` to match `{profile_id}` (a profile can only delete itself) — 403 otherwise.
- `GET /api/conversations/unclaimed-summary` — `{count: N}`. No header required. Used by the picker to decide whether to offer "Import existing conversations."
- `POST /api/profiles/{profile_id}/claim-unclaimed` — sets `profile_id` on every currently-unclaimed conversation to `{profile_id}`. Idempotent: running it twice only claims what's still unclaimed at call time, so it's safe to expose without extra guarding.

## Frontend UX

- New gate on app load: read the active profile id from `localStorage`. If present and still resolves via `GET /api/profiles`, skip straight to the existing landing page with that profile active. If missing or stale (e.g. the profile was deleted from another browser), show the new profile picker.
- **Profile picker**: a card grid — same visual language as the advisor gallery's "+ Add Advisor" tile (`AdvisorSetup.jsx`/`.css`) for consistency — one card per profile (avatar emoji, name, color-accented border) plus a dashed "+ Add Profile" tile. If `GET /api/conversations/unclaimed-summary` reports `count > 0` and this browser has never stored an active profile before, also show an "Import N existing conversations" affordance that triggers the claim endpoint right after the next profile is picked/created.
- **Switching profiles**: a small control in `Sidebar.jsx` shows the active profile's avatar/name and offers "Switch Profile," which clears the stored active profile id and returns to the picker (no server-side logout needed, since there's no server-side session).
- **Deleting your own profile**: a confirmation modal states how many private conversations will be deleted, then calls `DELETE /api/profiles/{id}`, clears `localStorage`, and returns to the picker.

## Error handling and compatibility

- Missing/unknown `X-Profile-Id` on a conversation endpoint → `400`. The frontend should never trigger this once a profile is active, but it protects against stale clients or direct API use.
- Accessing another profile's conversation by ID → `404`, not `403` (don't leak existence).
- Duplicate profile names are allowed; ids get a numeric suffix on collision, matching the existing custom-persona behavior.
- Deleting the last remaining profile is allowed; the next load simply shows an empty picker with only the "+ Add Profile" tile, identical to first-ever run.
- `/api/ask` and the MCP server keep working exactly as they do today for callers that never pass `profile_id` — their conversations are just unclaimed, not broken or rejected.

## Testing

- New `backend/tests/test_profiles.py`, mirroring the structure of `backend/tests/test_personas.py`: create/list/delete, slug collision handling, and a fixture that isolates `data/profiles.json` the same way persona tests isolate `persona_overrides.json`.
- Extend `backend/tests/test_storage_modes.py` (or a new focused test module) to cover: list/get/delete filtering by `profile_id`, cross-profile access returning `404`, and unclaimed-conversation semantics (`profile_id: null` excluded from every profile's list, but still fetchable by ID directly).
- Cover `claim-unclaimed` idempotency: calling it twice doesn't re-touch already-claimed conversations, and calling it with no unclaimed conversations is a no-op, not an error.
- No new frontend automated tests — matches the project's existing testing posture, where the frontend has only `npm run lint` and no test runner configured in `package.json`.

## Documentation synchronization

Per `docs/DOC-SYNC.md`, this needs updates to: `README.md` (mention profiles alongside existing features), `docs/mcp/*.md` (document the optional `profile_id` field on `/api/ask` and MCP-originated conversations), and `CHANGELOG.md` under the next unreleased section. Deferred to the implementation plan rather than detailed here.
