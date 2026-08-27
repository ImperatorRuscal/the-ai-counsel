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
