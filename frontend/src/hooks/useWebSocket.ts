import { useEffect, useRef } from 'react'
import { wsService } from '@/services/ws'
import { useWSStore } from '@/stores/wsStore'

interface UseWebSocketReturn {
  status: 'connecting' | 'connected' | 'disconnected'
  reconnectAttempts: number
}

/**
 * Connects the singleton WebSocket service on first mount.
 * Only the first caller owns the lifecycle; subsequent callers just read status.
 * This prevents the double-connect race when used in both App and a page component.
 */
let _mountCount = 0

export function useWebSocket(): UseWebSocketReturn {
  const status = useWSStore((s) => s.status)
  const reconnectAttempts = useWSStore((s) => s.reconnectAttempts)
  const isOwner = useRef(false)

  useEffect(() => {
    _mountCount++
    if (_mountCount === 1) {
      isOwner.current = true
      wsService.connect()
    }
    return () => {
      _mountCount--
      // Only disconnect when the very last consumer unmounts (i.e. app teardown)
      if (isOwner.current && _mountCount === 0) {
        wsService.disconnect()
      }
    }
  }, [])

  return { status, reconnectAttempts }
}
