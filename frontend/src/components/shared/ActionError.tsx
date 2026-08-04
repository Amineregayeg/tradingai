import { Banner } from '@/components/ui'

/**
 * Reports that a control you pressed did not do what you asked (E5).
 *
 * Rendered NEXT TO the controls rather than at the top of the page: the whole
 * failure being fixed is that a button appeared to work, so the correction
 * belongs where the button is, not somewhere the eye has already left.
 *
 * Dismissible because it describes a past event, not a present condition —
 * unlike LoadFailure, which stays until the data actually loads.
 */
export function ActionError({ message, onDismiss }: { message: string | null; onDismiss?: () => void }) {
  if (!message) return null
  return (
    <div style={{ marginTop: 10 }}>
      <Banner variant="error" dismissible onDismiss={onDismiss}>
        {message}
      </Banner>
    </div>
  )
}
