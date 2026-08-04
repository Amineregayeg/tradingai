import { useCallback, useState } from 'react'

/**
 * Run a user-triggered action and SAY SO when it fails (E5).
 *
 * THE BUG THIS EXISTS TO KILL
 * Every control on the app ended in `.catch(() => {})`:
 *
 *     onClick={() => api.engine.pause().then(setStatus).catch(() => {})}
 *
 * You press Pause. Nothing visibly fails. The engine keeps trading. The
 * operator's belief and the system's actual state diverge, with no signal that
 * they have — which is the same defect as E3 pointed the other way: E3 was the
 * page claiming something false about the data, this is the page claiming
 * something false about what you just did.
 *
 * WHY IT RE-READS AFTERWARDS RATHER THAN TRUSTING THE RESPONSE
 * These actions previously set local state from the reply (`.then(setStatus)`),
 * so the UI showed the outcome the request *claimed*. Callers pair `run` with a
 * reload of real state, because the question that matters after pressing Pause
 * is not "did the request return 200" but "is the engine paused now".
 *
 * `run` takes a thunk, not a promise, so nothing is in flight until it is
 * called — a promise built at render time would fire on every render and could
 * reject with nobody listening.
 */

/** Pull something readable out of whatever the API layer threw. */
export function actionMessage(e: unknown): string {
  if (e === null || e === undefined) return 'unknown error'
  if (typeof e === 'string') return e
  if (e instanceof Error && e.message) return e.message

  const shape = e as { detail?: unknown; title?: unknown; status?: unknown; statusText?: unknown }
  // The api layer throws RFC7807-shaped objects: { type, title, status, detail }.
  if (typeof shape.detail === 'string' && shape.detail) return shape.detail
  if (typeof shape.title === 'string' && shape.title) return shape.title
  // The CSV export throws the raw Response instead.
  if (typeof shape.status === 'number') {
    const text = typeof shape.statusText === 'string' && shape.statusText ? ` ${shape.statusText}` : ''
    return `HTTP ${shape.status}${text}`
  }
  return 'unknown error'
}

/**
 * Explicitly ok-or-not, rather than "undefined means it failed".
 *
 * That shortcut would be wrong here: the api layer returns `undefined` for a
 * 204, which several of these endpoints answer with on SUCCESS. A caller
 * reverting an optimistic update on `undefined` would undo changes that
 * actually saved.
 */
export type ActionResult<T> = { ok: true; value: T } | { ok: false; message: string }

export function useAction() {
  const [error, setError] = useState<string | null>(null)
  /** Label of the action currently in flight, for disabling its control. */
  const [pending, setPending] = useState<string | null>(null)

  const run = useCallback(
    async <T,>(label: string, work: () => Promise<T>): Promise<ActionResult<T>> => {
      setPending(label)
      setError(null)
      try {
        return { ok: true, value: await work() }
      } catch (e) {
        const message = `${label} failed — ${actionMessage(e)}`
        setError(message)
        return { ok: false, message }
      } finally {
        setPending(null)
      }
    },
    []
  )

  const dismiss = useCallback(() => setError(null), [])

  return { error, pending, run, dismiss }
}
