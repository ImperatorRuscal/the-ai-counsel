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
