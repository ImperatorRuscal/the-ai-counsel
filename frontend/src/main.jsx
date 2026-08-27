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
