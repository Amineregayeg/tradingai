import { describe, it, expect } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useLoadState } from '@/hooks/useLoadState'

/**
 * The property under test is that a failed load cannot be mistaken for an empty
 * result (KNOWN_ISSUES E3).
 *
 * Seven pages used to write `.catch(() => setTrades([]))`, so an outage and a
 * genuinely quiet week rendered identically — and the quiet week is the reading
 * people accept without checking. These tests pin both halves of the fix: the
 * fallback still arrives (so a page keeps rendering what it has), AND the
 * failure is recorded (so the page can say the figures are incomplete).
 */
describe('useLoadState', () => {
  it('returns the fallback and records the failure', async () => {
    const { result } = renderHook(() => useLoadState())

    let value: number[] | undefined
    await act(async () => {
      value = await result.current.track('trades', Promise.reject(new Error('boom')), [])
    })

    expect(value).toEqual([])
    expect(result.current.failed).toEqual(['trades'])
  })

  it('records nothing when the load succeeds', async () => {
    const { result } = renderHook(() => useLoadState())

    let value: number[] | undefined
    await act(async () => {
      value = await result.current.track('trades', Promise.resolve([1, 2]), [])
    })

    expect(value).toEqual([1, 2])
    expect(result.current.failed).toEqual([])
  })

  it('clears a failure once the same load succeeds again', async () => {
    // Polling pages must heal without a reload; a banner that never goes away
    // is the kind of warning people learn to ignore.
    const { result } = renderHook(() => useLoadState())

    await act(async () => {
      await result.current.track('trades', Promise.reject(new Error('x')), [])
    })
    expect(result.current.failed).toEqual(['trades'])

    await act(async () => {
      await result.current.track('trades', Promise.resolve([1]), [])
    })
    await waitFor(() => expect(result.current.failed).toEqual([]))
  })

  it('does not list the same failure twice', async () => {
    const { result } = renderHook(() => useLoadState())

    await act(async () => {
      await result.current.track('trades', Promise.reject(new Error('x')), [])
      await result.current.track('trades', Promise.reject(new Error('x')), [])
    })

    expect(result.current.failed).toEqual(['trades'])
  })

  it('tracks several loads independently', async () => {
    // Pages load more than one thing, and "trades could not be loaded" is
    // actionable where "something failed" is not.
    const { result } = renderHook(() => useLoadState())

    await act(async () => {
      await Promise.all([
        result.current.track('trades', Promise.reject(new Error('x')), []),
        result.current.track('alerts', Promise.resolve([1]), []),
        result.current.track('positions', Promise.reject(new Error('x')), []),
      ])
    })

    expect(result.current.failed).toContain('trades')
    expect(result.current.failed).toContain('positions')
    expect(result.current.failed).not.toContain('alerts')
  })

  it('keeps a rejection from propagating to the caller', async () => {
    // A page that throws on one failed request loses the sections that DID
    // load — a worse outage than a partial one.
    const { result } = renderHook(() => useLoadState())

    await expect(
      act(async () => {
        await result.current.track('trades', Promise.reject(new Error('boom')), null)
      })
    ).resolves.not.toThrow()
  })
})
