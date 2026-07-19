import { useState } from 'react'
import { getToken, setToken } from '@/services/api'

/**
 * Single-user auth gate. The API requires a bearer token on every route; this
 * collects it once, stores it in localStorage, and only then renders the app.
 * A 401 anywhere clears the token (see api.ts) and reloads, which brings this
 * gate back. This is NOT a security boundary by itself — it pairs with the
 * server, which refuses to start unauthenticated and 401s every request.
 */
export function LoginGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean>(() => !!getToken())
  const [value, setValue] = useState('')

  if (authed) return <>{children}</>

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!value.trim()) return
    setToken(value)
    setAuthed(true)
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#0a0a0f',
    }}>
      <form onSubmit={submit} style={{
        width: 360, background: '#12121a', border: '1px solid #1e2035', borderRadius: 14,
        padding: '28px 26px', display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#e8e8ef' }}>Trading AI</div>
          <div style={{ fontSize: 12, color: '#8888a0', marginTop: 4 }}>
            Enter your access token to continue.
          </div>
        </div>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Access token"
          autoFocus
          style={{
            background: '#0a0a0f', border: '1px solid #252540', borderRadius: 8,
            padding: '10px 12px', color: '#e8e8ef', fontSize: 14, fontFamily: 'var(--font-mono)',
          }}
        />
        <button
          type="submit"
          style={{
            padding: '10px 14px', border: 'none', borderRadius: 8, background: '#a78bfa',
            color: '#12121a', fontSize: 14, fontWeight: 700, cursor: 'pointer',
          }}
        >Enter</button>
        <div style={{ fontSize: 11, color: '#55556a', lineHeight: 1.5 }}>
          The token is stored only in this browser. If it's wrong, requests return 401 and you'll be asked again.
        </div>
      </form>
    </div>
  )
}
