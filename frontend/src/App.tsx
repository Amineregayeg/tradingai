import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { SharedLayout } from '@/components/layout/SharedLayout'
import { LoginGate } from '@/components/auth/LoginGate'
import { useSettingsStore } from '@/stores/settingsStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { api } from '@/services/api'

const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const JournalPage = lazy(() => import('@/pages/JournalPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const PropFirmPage = lazy(() => import('@/pages/PropFirmPage'))
const ChecklistPage = lazy(() => import('@/pages/ChecklistPage'))
const WeeklyReviewPage = lazy(() => import('@/pages/WeeklyReviewPage'))
const MorningBriefingPage = lazy(() => import('@/pages/MorningBriefingPage'))
const ReportPage = lazy(() => import('@/pages/ReportPage'))
const EnginePage = lazy(() => import('@/pages/EnginePage'))

const Fallback = () => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    flex: 1, background: '#0a0a0f',
  }}>
    <div style={{
      width: 32, height: 32, border: '2px solid #a78bfa',
      borderTopColor: 'transparent', borderRadius: '50%',
      animation: 'spin 0.8s linear infinite',
    }} />
  </div>
)

// Everything that requires a valid token lives here, so it only mounts AFTER the
// LoginGate has a token. Running the WS connection / settings fetch before login
// would 401 (and the WS retry loop would hammer the ws-ticket endpoint into a
// rate limit), so they must not run on the login screen.
function AuthedShell() {
  const setSettings = useSettingsStore((s) => s.setSettings)
  useWebSocket()

  useEffect(() => {
    api.settings.get().then(setSettings).catch(() => {})
  }, [setSettings])

  return (
    <Suspense fallback={<Fallback />}>
      <Routes>
        <Route element={<SharedLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/engine" element={<EnginePage />} />
          <Route path="/journal" element={<JournalPage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/prop-firm" element={<PropFirmPage />} />
          <Route path="/checklist" element={<ChecklistPage />} />
          <Route path="/weekly" element={<WeeklyReviewPage />} />
          <Route path="/briefing" element={<MorningBriefingPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <LoginGate>
      <AuthedShell />
    </LoginGate>
  )
}
