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
  const [importExisting, setImportExisting] = useState(false);
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
