import { AlertTriangle, ArrowRight, BadgeCheck, Bot, Clock, Euro, Package, ShieldAlert, UserRound } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router'
import { ErrorNote, PageHeader } from '@/components/common'
import { StatusBadge } from '@/components/status'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { usePoll } from '@/lib/api'
import { ago, eur, num, shortDate, shortId } from '@/lib/format'
import { orderPhase, PHASES, type Phase } from '@/lib/pipeline'
import type { AdminClient, AdminLogEntry, AdminOrder } from '@/lib/types'
import { cn } from '@/lib/utils'
import { OrdersChart } from './orders-chart'
import { RangePicker, useRange } from './range'

/** Groups the server's rejection reasons by the kind of rule, for display only. */
function rejectionKind(reason: string): string {
  const r = reason.toLowerCase()
  if (r.includes('mandate was not accepted') || r.includes('signature')) return 'Mandate missing, expired or not validly signed'
  if (r.includes('category')) return 'Category not allowed by the mandate'
  if (r.includes('allergen')) return 'Blocked allergen'
  if (r.includes('already been used')) return 'Quote reused by another buyer'
  if (r.includes('quote')) return 'Quote changed, expired or unknown'
  if (r.includes('rejected by')) return 'Rejected by a person at the buyer'
  if (r.includes('deliver') || r.includes('arrive')) return 'Cannot arrive by the need-by date'
  return reason.split('. ')[0].slice(0, 100)
}

function Kpi({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <Card className="gap-2 p-4">
      <div className="flex items-center justify-between text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
        {label}
        <span className="text-primary">{icon}</span>
      </div>
      <div className="text-[26px] leading-none font-semibold text-emphasis tnum">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </Card>
  )
}

export default function OpsDashboard() {
  const { since, label, range } = useRange()
  const q = since ? `?since=${encodeURIComponent(since)}` : ''
  const { data: orders, error, reload } = usePoll<AdminOrder[]>(`/admin/orders${q}`, 5000)
  const { data: clients } = usePoll<AdminClient[]>('/admin/clients', 5000)
  const { data: log } = usePoll<AdminLogEntry[]>(`/admin/log${q}`, 8000)

  const stats = useMemo(() => {
    const counts = Object.fromEntries(PHASES.map((p) => [p.key, 0])) as Record<Phase, number>
    const perClient = new Map<string, { orders: number; value: number; open: number }>()
    let value = 0
    for (const o of orders ?? []) {
      const phase = orderPhase(o)
      counts[phase] += 1
      const c = perClient.get(o.buyer_id) ?? { orders: 0, value: 0, open: 0 }
      c.orders += 1
      if (o.status === 'confirmed') {
        c.value += o.total_eur
        value += o.total_eur
      }
      if (phase === 'awaiting_approval') c.open += 1
      perClient.set(o.buyer_id, c)
    }
    const total = orders?.length ?? 0
    const auto = (orders ?? []).filter((o) => o.status === 'confirmed' && !o.approval).length
    return { counts, perClient, value, total, auto }
  }, [orders])

  const attention = (orders ?? [])
    .filter((o) => o.status === 'pending_approval')
    .sort((a, b) => a.created_at.localeCompare(b.created_at))

  const reasons = useMemo(() => {
    const m = new Map<string, number>()
    for (const e of log ?? []) {
      if (e.action !== 'decision:rejected' && e.action !== 'approval:rejected') continue
      const key = rejectionKind(e.reason)
      m.set(key, (m.get(key) ?? 0) + 1)
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
  }, [log])

  const decisions = (log ?? []).filter((e) => e.action.startsWith('decision:') || e.action.startsWith('approval:') || e.action === 'mandate:updated').slice(-8).reverse()
  const clientName = (id: string | null) => clients?.find((c) => c.buyer_id === id)?.name ?? id ?? '—'
  const running = (clients ?? []).filter((c) => c.agent_running).length

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Valio Aimo · Trade operations"
        title="Dashboard"
        sub="Every buyer agent ordering through the MCP front door, and what the rules decided."
        actions={<RangePicker />}
      />
      <ErrorNote error={error} onRetry={reload} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi icon={<Package className="size-4" />} label={`Orders · ${label}`} value={num(stats.total)} sub={stats.total ? `${Math.round((stats.auto / stats.total) * 100)}% confirmed by the rules alone` : undefined} />
        <Kpi icon={<Euro className="size-4" />} label="Confirmed value" value={eur(stats.value)} sub="without VAT" />
        <Kpi icon={<UserRound className="size-4" />} label="Waiting on buyers" value={num(attention.length)} sub="input or approval" />
        <Kpi icon={<Bot className="size-4" />} label="Clients connected" value={`${running} / ${clients?.length ?? 0}`} sub="agents working right now" />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="gap-3 p-5">
          <h2 className="text-base font-semibold text-emphasis">Orders placed per {range === '24h' ? 'hour' : 'day'}</h2>
          {orders ? <OrdersChart orders={orders} since={since} hourly={range === '24h'} /> : <Skeleton className="h-40 w-full" />}
        </Card>

        <Card className="gap-0 p-0">
          <CardHeader className="flex flex-row items-center gap-2 border-b py-3!">
            <AlertTriangle className="size-4 text-wait" aria-hidden />
            <CardTitle className="text-base">Waiting on buyers</CardTitle>
            <Link to="/server/orders?phase=open" className="ml-auto text-xs text-primary hover:underline">
              All
            </Link>
          </CardHeader>
          {attention.length === 0 ? (
            <p className="p-5 text-sm text-muted-foreground">Nothing is waiting. Every order is decided.</p>
          ) : (
            <ul className="divide-y">
              {attention.slice(0, 6).map((o) => (
                <li key={o.order_id}>
                  <Link to={`/server/orders/${o.order_id}`} className="flex items-start gap-3 px-5 py-3 hover:bg-muted/40">
                    <UserRound className="mt-0.5 size-4 shrink-0 text-wait" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-sm">
                        <span className="truncate font-medium">{o.buyer_name}</span>
                        <span className="ml-auto shrink-0 font-semibold tnum">{eur(o.total_eur)}</span>
                      </div>
                      <div className="truncate text-xs text-muted-foreground">{o.reasons[0]}</div>
                      <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                        <Clock className="size-3" /> {ago(o.created_at)}
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* Clients */}
      <Card className="gap-0 p-0">
        <CardHeader className="border-b py-3!">
          <CardTitle className="text-base">Clients</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              <tr>
                <th className="px-5 py-2.5">Client</th>
                <th className="px-3 py-2.5">Agent</th>
                <th className="px-3 py-2.5">Mandate</th>
                <th className="px-3 py-2.5 text-right">Orders · {label}</th>
                <th className="px-3 py-2.5 text-right">Confirmed value</th>
                <th className="px-5 py-2.5 text-right">Waiting</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {(clients ?? []).map((c) => {
                const s = stats.perClient.get(c.buyer_id)
                return (
                  <tr key={c.buyer_id} className="hover:bg-muted/30">
                    <td className="px-5 py-3">
                      <Link to={`/server/orders?client=${c.buyer_id}`} className="font-medium text-emphasis hover:underline">
                        {c.name}
                      </Link>
                      <div className="font-mono text-[11px] text-muted-foreground">{c.agent_id}</div>
                    </td>
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center gap-1.5 text-xs">
                        <span className={cn('size-2 rounded-full', c.agent_running ? 'bg-go' : 'bg-muted-foreground/40')} />
                        {c.agent_running ? 'Working now' : c.last_seen ? `Seen ${ago(c.last_seen)}` : 'Not seen'}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs">
                      {c.mandate_verified ? (
                        <span className="inline-flex items-center gap-1 text-ok">
                          <BadgeCheck className="size-3.5" /> Signed · until {shortDate(c.valid_until)}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-stop">
                          <ShieldAlert className="size-3.5" /> {c.mandate_problem ?? 'Not valid'}
                        </span>
                      )}
                      {c.mandate_id && <div className="font-mono text-[10px] text-muted-foreground">{c.mandate_id}</div>}
                    </td>
                    <td className="px-3 py-3 text-right tnum">{num(s?.orders ?? 0)}</td>
                    <td className="px-3 py-3 text-right tnum">{eur(s?.value ?? 0)}</td>
                    <td className="px-5 py-3 text-right tnum">
                      {s?.open ? <span className="rounded-full bg-wait-soft px-2 py-0.5 text-xs font-semibold text-wait">{s.open}</span> : '0'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="gap-0 p-0">
          <CardHeader className="flex flex-row items-center border-b py-3!">
            <CardTitle className="text-base">Latest decisions</CardTitle>
            <Link to="/server/log" className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline">
              Audit log <ArrowRight className="size-3" />
            </Link>
          </CardHeader>
          {decisions.length === 0 ? (
            <p className="p-5 text-sm text-muted-foreground">No decisions in this period.</p>
          ) : (
            <ul className="divide-y">
              {decisions.map((e) => {
                const status = e.action.split(':')[1]
                return (
                  <li key={e.seq} className="px-5 py-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      {e.action === 'mandate:updated' ? (
                        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">Mandate updated</span>
                      ) : (
                        <StatusBadge status={status} />
                      )}
                      <span className="font-medium">{clientName(e.buyer_id)}</span>
                      {e.order_id && (
                        <Link to={`/server/orders/${e.order_id}`} className="font-mono text-xs text-muted-foreground hover:underline">
                          {shortId(e.order_id)}
                        </Link>
                      )}
                      <span className="ml-auto text-xs text-muted-foreground">{ago(e.time)}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-muted-foreground">{e.reason}</p>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>

        <Card className="gap-0 p-0">
          <CardHeader className="border-b py-3!">
            <CardTitle className="text-base">Why orders were rejected</CardTitle>
          </CardHeader>
          {reasons.length === 0 ? (
            <p className="p-5 text-sm text-muted-foreground">No rejections in this period.</p>
          ) : (
            <ul className="divide-y">
              {reasons.map(([r, n]) => (
                <li key={r} className="flex items-start gap-3 px-5 py-3 text-sm">
                  <span className="rounded-full bg-stop-soft px-2 py-0.5 text-xs font-semibold text-stop tnum">{n}</span>
                  <span className="text-foreground/85">{r}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
