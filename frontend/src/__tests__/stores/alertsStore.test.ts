import { describe, it, expect, beforeEach } from 'vitest'
import { useAlertsStore } from '@/stores/alertsStore'
import type { Alert } from '@/types/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 'alert-1',
    user_id: 'system',
    type: 'ENTRY_SIGNAL',
    priority: 'SUGGESTION',
    status: 'PENDING',
    title: 'Test Alert',
    message: 'This is a test alert message.',
    pair: 'EURUSD',
    suggested_action: { sl: 1.080, tp: 1.095, lot_size: 0.1 },
    context_json: {},
    ai_confidence: null,
    score: null,
    entry_price: 1.085,
    sl_price: 1.080,
    tp_price: 1.095,
    r_ratio: 2.0,
    lot_size: 0.1,
    expires_at: null,
    created_at: '2024-05-16T14:00:00.000Z',
    resolved_at: null,
    resolved_by: null,
    ...overrides,
  }
}

// ─── Reset store before each test ────────────────────────────────────────────

beforeEach(() => {
  useAlertsStore.setState({ pending: [], history: [], badge: 0 })
})

// ─── Initial state ────────────────────────────────────────────────────────────

describe('alertsStore — initial state', () => {
  it('starts with empty pending array', () => {
    const { pending } = useAlertsStore.getState()
    expect(pending).toHaveLength(0)
  })

  it('starts with empty history array', () => {
    const { history } = useAlertsStore.getState()
    expect(history).toHaveLength(0)
  })

  it('starts with badge count of 0', () => {
    const { badge } = useAlertsStore.getState()
    expect(badge).toBe(0)
  })
})

// ─── addAlert ─────────────────────────────────────────────────────────────────

describe('addAlert', () => {
  it('adds a PENDING alert to pending array', () => {
    const alert = makeAlert({ status: 'PENDING' })
    useAlertsStore.getState().addAlert(alert)
    expect(useAlertsStore.getState().pending).toContainEqual(alert)
  })

  it('increments badge for PENDING alert', () => {
    useAlertsStore.getState().addAlert(makeAlert({ status: 'PENDING' }))
    expect(useAlertsStore.getState().badge).toBe(1)
  })

  it('increments badge by 1 for each PENDING alert added', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a1', status: 'PENDING' }))
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a2', status: 'PENDING' }))
    expect(useAlertsStore.getState().badge).toBe(2)
  })

  it('does NOT add non-PENDING alert to pending array', () => {
    const alert = makeAlert({ status: 'APPROVED' })
    useAlertsStore.getState().addAlert(alert)
    expect(useAlertsStore.getState().pending).toHaveLength(0)
  })

  it('adds non-PENDING alert directly to history', () => {
    const alert = makeAlert({ status: 'APPROVED' })
    useAlertsStore.getState().addAlert(alert)
    expect(useAlertsStore.getState().history).toContainEqual(alert)
  })

  it('does NOT increment badge for non-PENDING alert', () => {
    useAlertsStore.getState().addAlert(makeAlert({ status: 'REJECTED' }))
    expect(useAlertsStore.getState().badge).toBe(0)
  })
})

// ─── resolveAlert ─────────────────────────────────────────────────────────────

describe('resolveAlert', () => {
  it('removes resolved alert from pending', () => {
    const alert = makeAlert({ id: 'a1', status: 'PENDING' })
    useAlertsStore.getState().addAlert(alert)
    useAlertsStore.getState().resolveAlert('a1', 'APPROVED')
    expect(useAlertsStore.getState().pending.find((a) => a.id === 'a1')).toBeUndefined()
  })

  it('moves resolved alert to history with new status', () => {
    const alert = makeAlert({ id: 'a1', status: 'PENDING' })
    useAlertsStore.getState().addAlert(alert)
    useAlertsStore.getState().resolveAlert('a1', 'APPROVED')
    const inHistory = useAlertsStore.getState().history.find((a) => a.id === 'a1')
    expect(inHistory).toBeDefined()
    expect(inHistory?.status).toBe('APPROVED')
  })

  it('resolves with REJECTED status correctly', () => {
    const alert = makeAlert({ id: 'a1', status: 'PENDING' })
    useAlertsStore.getState().addAlert(alert)
    useAlertsStore.getState().resolveAlert('a1', 'REJECTED')
    const inHistory = useAlertsStore.getState().history.find((a) => a.id === 'a1')
    expect(inHistory?.status).toBe('REJECTED')
  })

  it('does nothing when alert ID not found', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a1', status: 'PENDING' }))
    useAlertsStore.getState().resolveAlert('nonexistent', 'APPROVED')
    expect(useAlertsStore.getState().pending).toHaveLength(1)
  })

  it('prepends resolved alert to history (newest first)', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a1', status: 'PENDING' }))
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a2', status: 'APPROVED' })) // goes to history directly
    useAlertsStore.getState().resolveAlert('a1', 'APPROVED')
    const history = useAlertsStore.getState().history
    expect(history[0].id).toBe('a1') // most recently resolved is first
  })
})

// ─── expireAlert ──────────────────────────────────────────────────────────────

describe('expireAlert', () => {
  it('removes expired alert from pending', () => {
    const alert = makeAlert({ id: 'a1', status: 'PENDING' })
    useAlertsStore.getState().addAlert(alert)
    useAlertsStore.getState().expireAlert('a1')
    expect(useAlertsStore.getState().pending.find((a) => a.id === 'a1')).toBeUndefined()
  })

  it('moves expired alert to history with EXPIRED status', () => {
    const alert = makeAlert({ id: 'a1', status: 'PENDING' })
    useAlertsStore.getState().addAlert(alert)
    useAlertsStore.getState().expireAlert('a1')
    const inHistory = useAlertsStore.getState().history.find((a) => a.id === 'a1')
    expect(inHistory?.status).toBe('EXPIRED')
  })

  it('does nothing when alert ID not found', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a1', status: 'PENDING' }))
    useAlertsStore.getState().expireAlert('nonexistent')
    expect(useAlertsStore.getState().pending).toHaveLength(1)
  })
})

// ─── loadPending ──────────────────────────────────────────────────────────────

describe('loadPending', () => {
  it('replaces pending with only PENDING-status alerts from the input list', () => {
    const alerts: Alert[] = [
      makeAlert({ id: 'p1', status: 'PENDING' }),
      makeAlert({ id: 'p2', status: 'PENDING' }),
      makeAlert({ id: 'r1', status: 'REJECTED' }), // should be filtered out
    ]
    useAlertsStore.getState().loadPending(alerts)
    const { pending } = useAlertsStore.getState()
    expect(pending).toHaveLength(2)
    expect(pending.every((a) => a.status === 'PENDING')).toBe(true)
  })

  it('sets badge to number of PENDING alerts', () => {
    const alerts: Alert[] = [
      makeAlert({ id: 'p1', status: 'PENDING' }),
      makeAlert({ id: 'p2', status: 'PENDING' }),
      makeAlert({ id: 'a1', status: 'APPROVED' }),
    ]
    useAlertsStore.getState().loadPending(alerts)
    expect(useAlertsStore.getState().badge).toBe(2)
  })

  it('replaces existing pending alerts entirely', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'old', status: 'PENDING' }))
    const newAlerts: Alert[] = [makeAlert({ id: 'new1', status: 'PENDING' })]
    useAlertsStore.getState().loadPending(newAlerts)
    const { pending } = useAlertsStore.getState()
    expect(pending).toHaveLength(1)
    expect(pending[0].id).toBe('new1')
  })

  it('sets pending to empty and badge to 0 when no PENDING alerts provided', () => {
    useAlertsStore.getState().loadPending([makeAlert({ status: 'APPROVED' })])
    expect(useAlertsStore.getState().pending).toHaveLength(0)
    expect(useAlertsStore.getState().badge).toBe(0)
  })
})

// ─── clearBadge ───────────────────────────────────────────────────────────────

describe('clearBadge', () => {
  it('resets badge to 0', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a1', status: 'PENDING' }))
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a2', status: 'PENDING' }))
    expect(useAlertsStore.getState().badge).toBe(2)
    useAlertsStore.getState().clearBadge()
    expect(useAlertsStore.getState().badge).toBe(0)
  })

  it('does not affect pending or history', () => {
    useAlertsStore.getState().addAlert(makeAlert({ id: 'a1', status: 'PENDING' }))
    useAlertsStore.getState().clearBadge()
    expect(useAlertsStore.getState().pending).toHaveLength(1)
  })
})
