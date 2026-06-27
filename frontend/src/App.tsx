import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { SharedLayout } from '@/components/layout/SharedLayout'
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

export default function App() {
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
