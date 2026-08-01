import { useEffect, useState } from 'react'
import { api } from '@/services/api'
import type { BrokerAccount } from '@/types/api'

/**
 * Live broker accounts — real balance and equity, read from the broker itself.
 *
 * Until this existed the platform could reach Crypto Fund Trader but nothing
 * displayed it, so "connected" was a claim with nothing behind it.
 *
 * THE DESIGN RULE HERE IS HONESTY OVER TIDINESS:
 *
 *  * An unreachable broker is SHOWN, in red, with the reason. Hiding it would
 *    read as "no such account".
 *  * A figure is rendered only when it was actually read just now. There is no
 *    cached fallback anywhere in this component — a stale balance presented as
 *    current is precisely the failure this project was rebuilt to remove, and
 *    it is worse than a blank, because a blank prompts a question.
 *  * "READ-ONLY" and "CAN TRADE" are stated explicitly. Whether a real-money
 *    connection is permitted to place orders should never require reading
 *    config to find out.
 */

const GREEN = '#00d68f'
const RED = '#ff3b5c'
const AMBER = '#e3b341'
const MUTED = '#55556a'

function money(v: number, ccy: string): string {
  const s = v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return ccy === 'USD' ? `$${s}` : `${s} ${ccy}`
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '3px 0' }}>
      <span style={{ fontSize: 11, color: MUTED }}>{label}</span>
      <span style={{ fontSize: 12, color: color ?? '#e8e8ef', fontFamily: 'var(--font-mono)' }}>{value}</span>
    </div>
  )
}

function AccountCard({ acc }: { acc: BrokerAccount }) {
  const live = acc.reachable && acc.account !== null
  const a = acc.account

  return (
    <div style={{
      background: '#12121a', border: '1px solid #1e2035', borderRadius: 9,
      padding: '11px 13px', marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: live ? GREEN : RED }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: '#e8e8ef' }}>{acc.broker}</span>
        {acc.is_simulation && (
          <span style={{ fontSize: 9, color: MUTED, border: `1px solid ${MUTED}`, borderRadius: 3, padding: '1px 4px' }}>
            SIM
          </span>
        )}
        {/* Order permission, stated rather than implied. */}
        <span style={{
          fontSize: 9, marginLeft: 'auto', padding: '1px 5px', borderRadius: 3,
          color: acc.observe_only ? MUTED : AMBER,
          border: `1px solid ${acc.observe_only ? MUTED : AMBER}`,
        }}>
          {acc.observe_only ? 'READ-ONLY' : 'CAN TRADE'}
        </span>
      </div>

      {live && a ? (
        <>
          <Row label="Balance" value={money(a.balance, a.currency)} />
          <Row label="Equity" value={money(a.equity, a.currency)} />
          {a.unrealized_pl !== 0 && (
            <Row
              label="Unrealized"
              value={`${a.unrealized_pl >= 0 ? '+' : ''}${money(a.unrealized_pl, a.currency)}`}
              color={a.unrealized_pl >= 0 ? GREEN : RED}
            />
          )}
          <Row label="Open positions" value={String(a.open_trade_count)} />
        </>
      ) : (
        // No figures at all when unreachable — deliberately. Showing the last
        // known balance here would be indistinguishable from a current one.
        <div style={{ fontSize: 11, color: RED, lineHeight: 1.5 }}>
          Cannot reach this account.
          <div style={{ color: MUTED, marginTop: 3, wordBreak: 'break-word' }}>
            {acc.error ?? 'no reason reported'}
          </div>
        </div>
      )}

      {/* Transport health, when the adapter reports it. Surfaced because "the
          browser session died" and "the broker rejected us" need different
          responses, and container logs are not a monitoring surface. */}
      {acc.transport && !acc.transport.reachable && (
        <div style={{ fontSize: 10, color: AMBER, marginTop: 6 }}>
          transport down: {acc.transport.error ?? 'unknown'}
        </div>
      )}
      {acc.transport?.reachable && acc.transport.last_error && (
        <div style={{ fontSize: 10, color: AMBER, marginTop: 6 }}>
          last transport error: {acc.transport.last_error}
        </div>
      )}
    </div>
  )
}

export function BrokerAccountsPanel() {
  const [accounts, setAccounts] = useState<BrokerAccount[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () => {
      api.brokers
        .accounts()
        .then((r) => { if (alive) { setAccounts(Array.isArray(r) ? r : []); setFailed(false) } })
        // Distinguish "the endpoint is down" from "no brokers configured".
        // Both would otherwise render as an empty panel.
        .catch(() => { if (alive) setFailed(true) })
    }
    load()
    // Balances move; 30s is frequent enough to be current without hammering a
    // broker API through a single browser session.
    const id = setInterval(load, 30_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (accounts === null && !failed) return null   // first load: say nothing yet
  if (failed) {
    return (
      <div style={{ padding: '10px 13px', fontSize: 11, color: RED }}>
        Broker accounts unavailable — the API did not respond.
      </div>
    )
  }
  if (accounts !== null && accounts.length === 0) return null  // none configured

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        fontSize: 10, color: MUTED, fontWeight: 700, letterSpacing: '0.07em',
        textTransform: 'uppercase', marginBottom: 7,
      }}>
        Broker Accounts
      </div>
      {accounts!.map((a) => <AccountCard key={a.connection_id} acc={a} />)}
    </div>
  )
}
