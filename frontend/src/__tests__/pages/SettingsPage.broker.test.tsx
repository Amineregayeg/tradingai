/**
 * B369 — the form must be able to PRODUCE the request the API accepts.
 *
 * THE AXIS, AND IT IS THE THIRD INSTANCE IN ONE DAY:
 *
 *     B356   the adapter's reading   vs   the SDK's actual return shape
 *     B368   the API's blob          vs   the factory's required blob
 *     B369   the UI's form           vs   the API's accepted schema
 *
 * Each is a producer and a consumer of one structure, verified only from the consumer's side,
 * with something hand-built standing in for the producer. B368's arm was fixed by DRIVING
 * `connect_broker` instead of constructing a blob; the same fix here means DRIVING THE FORM.
 *
 * **So no assertion below reads the component's source or its props.** An arm that checks a field
 * exists in the JSX proves the author added it. Only selecting the broker, typing into the inputs
 * and reading what `api.brokers.connect` was CALLED WITH proves a user can connect MT5.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const connect = vi.fn((_payload: Record<string, unknown>) =>
  Promise.resolve({ id: 'c1', broker: 'mt5' }))

vi.mock('@/services/api', () => ({
  authHeaders: () => ({}),
  api: {
    brokers: {
      list: () => Promise.resolve([]),
      connect: (payload: Record<string, unknown>) => connect(payload),
      disconnect: () => Promise.resolve({}),
    },
    settings: { get: () => Promise.resolve({}), update: () => Promise.resolve({}) },
  },
}))

import SettingsPage from '@/pages/SettingsPage'

async function openBrokerForm(user: ReturnType<typeof userEvent.setup>) {
  render(<SettingsPage />)
  // BY ROLE, NOT BY TEXT: the empty-state sentence also contains "Add Broker", so getByText
  // matches two nodes and throws — a failure that reads like the button being absent.
  const add = await screen.findByRole('button', { name: /Add Broker/i })
  await user.click(add)
}

describe('B369 — MT5 is reachable from the broker form', () => {
  beforeEach(() => { connect.mockClear() })

  it('offers MetaTrader 5 in the broker list at all', async () => {
    const user = userEvent.setup()
    await openBrokerForm(user)
    const select = screen.getByDisplayValue(/Crypto Fund Trader/i) as HTMLSelectElement
    const labels = Array.from(select.options).map((o) => o.textContent)
    expect(labels.some((l) => /MetaTrader 5/i.test(l ?? ''))).toBe(true)
  })

  it('SENDS token and mt5_account_id — not api_key — when MT5 is selected', async () => {
    const user = userEvent.setup()
    await openBrokerForm(user)

    const select = screen.getByDisplayValue(/Crypto Fund Trader/i) as HTMLSelectElement
    await user.selectOptions(select, 'mt5')

    await user.type(screen.getByPlaceholderText(/MetaApi API token/i), 'tok-abc')
    await user.type(screen.getByPlaceholderText(/provisioned account id/i), 'acct-123')
    await user.click(screen.getByRole('button', { name: /^Connect$/i }))

    await waitFor(() => expect(connect).toHaveBeenCalledTimes(1))
    const payload = connect.mock.calls[0]![0] as Record<string, unknown>

    expect(payload.broker).toBe('mt5')
    expect(payload.token).toBe('tok-abc')
    expect(payload.mt5_account_id).toBe('acct-123')
    // THE HALF THAT MATTERS AS MUCH: the token must not arrive in api_key. Overloading it was
    // the cheaper fix and was rejected — api_key means an exchange API key on every other
    // broker, and one field carrying two unrelated credentials is B184 at the inbound surface.
    expect(payload.api_key ?? '').not.toBe('tok-abc')
  })

  it('does NOT show the MetaApi fields for a non-MT5 broker', async () => {
    const user = userEvent.setup()
    await openBrokerForm(user)
    // The must-MISS: a branch added for one broker is one edit from rendering for all of them.
    expect(screen.queryByPlaceholderText(/MetaApi API token/i)).toBeNull()
    expect(screen.getByPlaceholderText(/account email/i)).toBeTruthy()
  })

  it('offers a Demo environment for MT5, which CFT does not have', async () => {
    const user = userEvent.setup()
    await openBrokerForm(user)
    const select = screen.getByDisplayValue(/Crypto Fund Trader/i) as HTMLSelectElement
    await user.selectOptions(select, 'mt5')
    // Offering only Live would repeat the CFT mistake in the opposite direction — sending a demo
    // user hunting for a mistake they did not make, which is what the header is about.
    expect(screen.getByText(/^Demo$/)).toBeTruthy()
  })

  // ────────────────────────────────────────────────────────────────────────────
  // B370 — what the note CLAIMS to the user
  // ────────────────────────────────────────────────────────────────────────────

  it('does not tell the user the environment is CHECKED against anything', async () => {
    const user = userEvent.setup()
    await openBrokerForm(user)
    const select = screen.getByDisplayValue(/Crypto Fund Trader/i) as HTMLSelectElement
    await user.selectOptions(select, 'mt5')

    // `_make_adapter`'s MT5 branch never reads `environment` — `practice`, `live` and `nonsense`
    // all construct. A note saying it MATCHES the provisioned account claims a check that does
    // not exist, so a typo is accepted in silence.
    // LOCATED BY A STABLE ANCHOR, NOT BY ITS OWN TEXT. Both arms first found the note by a
    // phrase that is itself under test, so a mutation to that phrase broke the LOCATOR and both
    // arms failed — one of them for a reason unrelated to its subject. A test that cannot find
    // its subject reports the same red as one whose subject is wrong.
    const note = screen.getByTestId('env-note')
    expect(note.textContent).toMatch(/NOT checked against MetaApi/i)
    expect(screen.queryByText(/Matches the MetaApi account you provisioned/i)).toBeNull()
  })

  it('does not name ONE blocker as the only thing between the user and trading', async () => {
    const user = userEvent.setup()
    await openBrokerForm(user)
    const select = screen.getByDisplayValue(/Crypto Fund Trader/i) as HTMLSelectElement
    await user.selectOptions(select, 'mt5')

    const note = screen.getByTestId('env-note').textContent ?? ''
    // "until the sizing conversion is settled" was accurate about WHERE and WHY and wrong about
    // SUFFICIENCY — and sufficiency is what a user reads. Four things stop an order, and the
    // last is a ruling only Malek can give.
    expect(note).not.toMatch(/until the sizing conversion is settled/i)
    expect(note).toMatch(/four things/i)
    expect(note).toMatch(/T-0076/)
    expect(note).toMatch(/no live mode/i)
  })
})
