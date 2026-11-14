import { Link2, Link2Off, Loader2, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Empty, ErrorNote, PageHeader } from '@/components/common'
import { LogTimeline } from '@/components/log-timeline'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccount } from '@/lib/account'
import { accountPath, api, usePoll, type ApiFailure } from '@/lib/api'
import { shortId } from '@/lib/format'
import type { LogEntry, Order, VerifyResult } from '@/lib/types'
import { cn } from '@/lib/utils'

export default function AuditLogPage() {
  const { buyerId, account } = useAccount()
  const { data, error, loading, reload } = usePoll<LogEntry[]>(buyerId ? accountPath(buyerId, '/log') : null, 5000)
  const { data: orders } = usePoll<Order[]>(buyerId ? accountPath(buyerId, '/orders') : null, 5000)
  const [verdict, setVerdict] = useState<VerifyResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [verifyError, setVerifyError] = useState<ApiFailure | null>(null)

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

  // Group by order; rows tied only to a quote join their order through quote_id.
  const groups = useMemo(() => {
    const byQuote = new Map((orders ?? []).map((o) => [o.quote_id, o.order_id]))
    const map = new Map<string, LogEntry[]>()
    for (const e of data ?? []) {
      const key = e.order_id ?? (e.quote_id ? byQuote.get(e.quote_id) : undefined) ?? e.quote_id ?? 'other'
      map.set(key, [...(map.get(key) ?? []), e])
    }
    return [...map.entries()].sort((a, b) => b[1][0].seq - a[1][0].seq)
  }, [data, orders])
  const orderById = new Map((orders ?? []).map((o) => [o.order_id, o]))

  return (
    <div>
      <PageHeader
        eyebrow={account?.name}
        title="Audit log"
        sub="The plain-language decision trail. Each entry is chained to the one before by its hash, so an edit anywhere breaks the chain."
        actions={
          <Button size="lg" onClick={verify} disabled={checking}>
            {checking ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Verify log
          </Button>
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
            ? 'Intact: every entry is chained, none edited.'
            : `Broken at entry ${verdict.broken_at_seq}: this entry was changed after it was written.`}
        </div>
      )}
      <ErrorNote error={verifyError ?? error} onRetry={verifyError ? verify : reload} />

      {loading && !data && <Skeleton className="h-60 w-full rounded-lg" />}
      {data && data.length === 0 && (
        <Empty icon={<ShieldCheck className="size-6" />} title="No entries for this account yet">
          Entries appear when this account’s agent quotes and orders.
        </Empty>
      )}

      <div className="space-y-4">
        {groups.map(([key, entries]) => {
          const o = orderById.get(key)
          return (
            <Card key={key} className="gap-0 p-0">
              <CardHeader className="flex flex-row flex-wrap items-center gap-2 border-b py-3!">
                <CardTitle className="font-mono text-sm">{o ? `Order ${shortId(o.order_id)}` : `Quote ${shortId(key)}`}</CardTitle>
                {o && (
                  <Link to={`/orders/${o.order_id}`} className="ml-auto text-xs text-primary hover:underline">
                    Delivery progress
                  </Link>
                )}
              </CardHeader>
              <LogTimeline entries={entries} brokenAt={verdict && !verdict.ok ? verdict.broken_at_seq : null} />
            </Card>
          )
        })}
      </div>
    </div>
  )
}
