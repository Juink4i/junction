import { Package } from 'lucide-react'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { Empty, ErrorNote, PageHeader } from '@/components/common'
import { OrderRow } from '@/components/order-row'
import { Skeleton } from '@/components/ui/skeleton'
import { usePoll } from '@/lib/api'
import { orderPhase, PHASES, type Phase } from '@/lib/pipeline'
import type { AdminClient, AdminOrder } from '@/lib/types'
import { cn } from '@/lib/utils'
import { RangePicker, useRange } from './range'

type PhaseFilter = Phase | 'open' | 'all'

export default function OpsOrders() {
  const { since } = useRange()
  const [params, setParams] = useSearchParams()
  const phase = (params.get('phase') ?? 'all') as PhaseFilter
  const client = params.get('client') ?? 'all'
  const q = since ? `?since=${encodeURIComponent(since)}` : ''
  const { data, error, loading, reload } = usePoll<AdminOrder[]>(`/admin/orders${q}`, 5000)
  const { data: clients } = usePoll<AdminClient[]>('/admin/clients', 15000)

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value === 'all') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: 0, open: 0 }
    for (const o of data ?? []) {
      if (client !== 'all' && o.buyer_id !== client) continue
      const p = orderPhase(o)
      c[p] = (c[p] ?? 0) + 1
      c.all += 1
      if (p === 'awaiting_input' || p === 'awaiting_approval') c.open += 1
    }
    return c
  }, [data, client])

  const shown = (data ?? []).filter((o) => {
    if (client !== 'all' && o.buyer_id !== client) return false
    const p = orderPhase(o)
    if (phase === 'all') return true
    if (phase === 'open') return p === 'awaiting_input' || p === 'awaiting_approval'
    return p === phase
  })

  const chips: { key: PhaseFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'open', label: 'Waiting on buyer' },
    ...PHASES.map((p) => ({ key: p.key as PhaseFilter, label: p.label })),
  ]

  return (
    <div>
      <PageHeader eyebrow="Valio Aimo · Trade operations" title="Orders" sub="Every client’s orders, with the server’s decision and delivery progress." actions={<RangePicker />} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          className="h-8 rounded-md border bg-card px-2 text-sm"
          value={client}
          onChange={(e) => set('client', e.target.value)}
          aria-label="Client"
        >
          <option value="all">All clients</option>
          {(clients ?? []).map((c) => (
            <option key={c.buyer_id} value={c.buyer_id}>
              {c.name}
            </option>
          ))}
        </select>
        {chips.map((c) => (
          <button
            key={c.key}
            onClick={() => set('phase', c.key)}
            aria-pressed={phase === c.key}
            className={cn(
              'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
              phase === c.key ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted',
            )}
          >
            {c.label} <span className="tnum opacity-75">{counts[c.key] ?? 0}</span>
          </button>
        ))}
      </div>

      <ErrorNote error={error} onRetry={reload} />
      {loading && !data && <Skeleton className="h-40 w-full rounded-lg" />}
      {data && shown.length === 0 && (
        <Empty icon={<Package className="size-6" />} title="No orders match">
          Try another client, stage or time range.
        </Empty>
      )}
      <div className="space-y-3">
        {shown.map((o) => (
          <OrderRow key={o.order_id} order={o} to={`/server/orders/${o.order_id}`} buyerName={o.buyer_name} />
        ))}
      </div>
    </div>
  )
}
