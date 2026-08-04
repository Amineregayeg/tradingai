import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAction, actionMessage } from '@/hooks/useAction'

/**
 * The property under test: a control that fails must say so (KNOWN_ISSUES E5).
 *
 * Every button ended in `.catch(() => {})`. You press Pause, nothing visibly
 * fails, and the engine keeps trading — the operator's belief and the system's
 * state diverge with no signal.
 */
describe('actionMessage', () => {
  it('prefers the API detail', () => {
    // The api layer throws RFC7807-shaped objects, not Errors.
    expect(actionMessage({ title: 'Request Failed', detail: 'engine is not running', status: 409 }))
      .toBe('engine is not running')
  })

  it('falls back to the title', () => {
    expect(actionMessage({ title: 'Conflict', status: 409 })).toBe('Conflict')
  })

  it('handles a raw Response, which the CSV export throws', () => {
    expect(actionMessage({ status: 502, statusText: 'Bad Gateway' })).toBe('HTTP 502 Bad Gateway')
  })

  it('handles an Error', () => {
    expect(actionMessage(new Error('network down'))).toBe('network down')
  })

  it('never returns an empty string', () => {
    for (const v of [null, undefined, {}, 0]) {
      expect(actionMessage(v).length).toBeGreaterThan(0)
    }
  })
})

describe('useAction', () => {
  it('reports success with the value', async () => {
    const { result } = renderHook(() => useAction())

    let r: any
    await act(async () => {
      r = await result.current.run('Pause', async () => 'paused')
    })

    expect(r).toEqual({ ok: true, value: 'paused' })
    expect(result.current.error).toBeNull()
  })

  it('treats an undefined return as SUCCESS, not failure', async () => {
    // The api layer returns undefined for a 204, which several of these
    // endpoints answer with on success. Inferring failure from `undefined`
    // would revert optimistic updates that actually saved — the exact bug this
    // hook's result shape exists to prevent.
    const { result } = renderHook(() => useAction())

    let r: any
    await act(async () => {
      r = await result.current.run('Saving', async () => undefined)
    })

    expect(r.ok).toBe(true)
    expect(result.current.error).toBeNull()
  })

  it('reports failure with a message naming the action', async () => {
    const { result } = renderHook(() => useAction())

    let r: any
    await act(async () => {
      r = await result.current.run('Pause', async () => {
        throw { title: 'Request Failed', detail: 'engine is not running', status: 409 }
      })
    })

    expect(r.ok).toBe(false)
    expect(result.current.error).toContain('Pause failed')
    expect(result.current.error).toContain('engine is not running')
  })

  it('never rethrows, so one failed control cannot break the page', async () => {
    const { result } = renderHook(() => useAction())

    await expect(
      act(async () => {
        await result.current.run('Reset run', async () => {
          throw new Error('boom')
        })
      })
    ).resolves.not.toThrow()
  })

  it('clears a previous error when a later action succeeds', async () => {
    const { result } = renderHook(() => useAction())

    await act(async () => {
      await result.current.run('Pause', async () => {
        throw new Error('boom')
      })
    })
    expect(result.current.error).not.toBeNull()

    await act(async () => {
      await result.current.run('Resume', async () => 'ok')
    })
    expect(result.current.error).toBeNull()
  })

  it('can be dismissed', async () => {
    const { result } = renderHook(() => useAction())

    await act(async () => {
      await result.current.run('Pause', async () => {
        throw new Error('boom')
      })
    })
    expect(result.current.error).not.toBeNull()

    act(() => result.current.dismiss())
    expect(result.current.error).toBeNull()
  })

  it('clears pending even when the action throws', async () => {
    // A control left disabled forever after one failure would be its own bug.
    const { result } = renderHook(() => useAction())

    await act(async () => {
      await result.current.run('Pause', async () => {
        throw new Error('boom')
      })
    })

    expect(result.current.pending).toBeNull()
  })
})
