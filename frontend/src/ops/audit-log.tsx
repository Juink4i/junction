import { Bot, Code2, Link2, Link2Off, Loader2, Search, ShieldCheck, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ErrorNote, PageHeader } from '@/components/common'
import { LogTimeline } from '@/components/log-timeline'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, usePoll, type ApiFailure } from '@/lib/api'
import { num } from '@/lib/format'
import type { AdminClient, AdminLogEntry, VerifyResult } from '@/lib/types'
import { cn } from '@/lib/utils'
import { RangePicker, useRange } from './range'

const ACTIONS = [
  { key: 'all', label: 'All actions' },
  { key: 'decision', label: 'Decisions' },
  { key: 'approval', label: 'Approvals' },
  { key: 'quote', label: 'Quotes & orders' },
  { key: 'search', label: 'Searches' },
  { key: 'mandate', label: 'Mandate changes' },
]

function matchesAction(action: string, key: string): boolean {
  if (key === 'all') return true
  if (key === 'decision') return action.startsWith('decision:')
  if (key === 'approval') return action.startsWith('approval:') || action === 'get_approval_status'
  if (key === 'quote') return action === 'request_quote' || action === 'place_order'
  if (key === 'search') return action === 'search_products' || action === 'get_product'
  if (key === 'mandate') return action.startsWith('mandate:')
  return true
}

function actorIcon(actor: string) {
  if (actor === 'policy') return Code2
  if (actor.includes('@')) return UserRound
  return Bot
}

/** The whole hash-chained log, per agent (actor), with Verify. */
export default function OpsAuditLog() {
  const { since } = useRange()
  const q = since ? `?since=${encodeURIComponent(since)}` : ''
  const { data, error, loading, reload } = usePoll<AdminLogEntry[]>(`/admin/log${q}`, 6000)
  const { data: clients } = usePoll<AdminClient[]>('/admin/clients', 15000)
  const [actor, setActor] = useState<string>('all')
  const [client, setClient] = useState<string>('all')
  const [action, setAction] = useState('all')
  const [text, setText] = useState('')
  const [limit, setLimit] = useState(200)
  const [verdict, setVerdict] = useState<VerifyResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [verifyError, setVerifyError] = useState<ApiFailure | null>(null)

  const actors = useMemo(() => {
    const m = new Map<string, number>()
    for (const e of data ?? []) m.set(e.actor, (m.get(e.actor) ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [data])

  const shown = useMemo(() => {
    const t = text.trim().toLowerCase()
    return (data ?? [])
      .filter(
        (e) =>
          (actor === 'all' || e.actor === actor) &&
          (client === 'all' || e.buyer_id === client) &&
          matchesAction(e.action, action) &&
          (!t || `${e.reason} ${e.action} ${e.order_id ?? ''} ${e.quote_id ?? ''}`.toLowerCase().includes(t)),
      )
      .slice()
      .reverse()
  }, [data, actor, client, action, text])

  const verify = async () => {
    setChecking(true)
    setVerifyError(null)
    try {
      setVerdict(await api<VerifyResult>('/log/verify'))
    } catch (e) {
      setVerifyError(e as ApiFailure)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Valio Aimo · Trade operations"
        title="Audit log"
        sub="Every search, quote, decision, approval and mandate change, from every agent. Each row is chained to the one before by its hash."
        actions={
          <>
            <RangePicker />
            <Button onClick={verify} disabled={checking}>
              {checking ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Verify log
            </Button>
          </>
        }
      />

      {verdict && (
        <div
          className={cn(
            'mb-5 flex items-center gap-3 rounded-xl border p-4 text-base font-semibold',
            verdict.ok ? 'border-ok/30 bg-ok-soft text-ok' : 'border-stop/30 bg-stop-soft text-stop',
          )}
          role="status"
        >
          {verdict.ok ? <Link2 className="size-6" /> : <Link2Off className="size-6" />}
          {verdict.ok
            ? `Intact: all ${num(data?.length ?? 0)}${since ? ' shown' : ''} entries are chained, none edited.`
            : `Broken at entry ${verdict.broken_at_seq}: this entry was changed after it was written.`}
        </div>
      )}
      <ErrorNote error={verifyError ?? error} onRetry={verifyError ? verify : reload} />

      <div className="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
        {/* Per agent */}
        <Card className="h-fit gap-0 p-2">
          <div className="px-2 py-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Agents & actors</div>
          <button
            onClick={() => setActor('all')}
            className={cn('flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm', actor === 'all' ? 'bg-secondary font-medium' : 'hover:bg-muted')}
          >
            Everyone <span className="text-xs text-muted-foreground tnum">{num(data?.length ?? 0)}</span>
          </button>
          {actors.map(([a, n]) => {
            const Icon = actorIcon(a)
            return (
              <button
                key={a}
                onClick={() => setActor(a)}
                className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm', actor === a ? 'bg-secondary font-medium' : 'hover:bg-muted')}
              >
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{a}</span>
                <span className="text-xs text-muted-foreground tnum">{n}</span>
              </button>
            )
          })}
        </Card>

        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-48 flex-1">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="pl-8" placeholder="Search reasons, order or quote ids" value={text} onChange={(e) => setText(e.target.value)} />
            </div>
            <select className="h-9 rounded-md border bg-card px-2 text-sm" value={client} onChange={(e) => setClient(e.target.value)} aria-label="Client">
              <option value="all">All clients</option>
              {(clients ?? []).map((c) => (
                <option key={c.buyer_id} value={c.buyer_id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select className="h-9 rounded-md border bg-card px-2 text-sm" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
              {ACTIONS.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
          <Card className="gap-0 p-0">
            {loading && !data ? (
              <Skeleton className="m-4 h-40" />
            ) : (
              <LogTimeline entries={shown.slice(0, limit)} brokenAt={verdict && !verdict.ok ? verdict.broken_at_seq : null} />
            )}
          </Card>
          {shown.length > limit && (
            <div className="text-center">
              <Button variant="outline" onClick={() => setLimit((l) => l + 200)}>
                Show more ({num(shown.length - limit)} older)
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
