import { Input, Select, Button } from '@/components/ui'

export interface TradeFilters {
  pair?: string
  outcome?: string
  from?: string
  to?: string
  search?: string
}

export interface TradeFiltersProps {
  filters: TradeFilters
  onChange: (filters: TradeFilters) => void
}

const outcomeOptions = [
  { value: '', label: 'All Outcomes' },
  { value: 'WIN', label: 'WIN' },
  { value: 'LOSS', label: 'LOSS' },
  { value: 'BE', label: 'BE' },
  { value: 'OPEN', label: 'OPEN' },
]

export function TradeFilters({ filters, onChange }: TradeFiltersProps) {
  const hasFilters = Object.values(filters).some((v) => v !== undefined && v !== '')

  const update = (key: keyof TradeFilters, value: string) => {
    onChange({ ...filters, [key]: value || undefined })
  }

  const clear = () => onChange({})

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: 'var(--space-3)',
        padding: 'var(--space-4)',
        paddingTop: 0,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ width: 140 }}>
        <Input
          label="Pair"
          placeholder="EUR/USD"
          value={filters.pair ?? ''}
          onChange={(e) => update('pair', e.target.value)}
        />
      </div>

      <div style={{ width: 160 }}>
        <Select
          label="Outcome"
          options={outcomeOptions}
          value={filters.outcome ?? ''}
          onChange={(e) => update('outcome', e.target.value)}
        />
      </div>

      <div style={{ width: 160 }}>
        <Input
          label="From"
          type="date"
          value={filters.from ?? ''}
          onChange={(e) => update('from', e.target.value)}
        />
      </div>

      <div style={{ width: 160 }}>
        <Input
          label="To"
          type="date"
          value={filters.to ?? ''}
          onChange={(e) => update('to', e.target.value)}
        />
      </div>

      <div style={{ width: 180 }}>
        <Input
          label="Search"
          placeholder="Setup tag, notes..."
          value={filters.search ?? ''}
          onChange={(e) => update('search', e.target.value)}
        />
      </div>

      {hasFilters && (
        <div style={{ paddingBottom: '2px' }}>
          <Button variant="ghost" size="sm" onClick={clear}>
            Clear filters
          </Button>
        </div>
      )}
    </div>
  )
}
