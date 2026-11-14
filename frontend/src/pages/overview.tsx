import { ArrowRight, Bot, ClipboardCheck, Receipt } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router'
import { LineTags } from '@/components/common'
import { EventFeed } from '@/components/feed'
import { Stepper } from '@/components/stepper'
import { LiveDot, StatusBadge } from '@/components/status'
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { useAccount } from '@/lib/account'
import { accountPath, useEvents, usePoll } from '@/lib/api'
import { eur, num, shortDate, unitsBothWays } from '@/lib/format'
import { latestRun, runView } from '@/lib/pipeline'
import type { Order, QuoteLine } from '@/lib/types'
import { ApprovalList } from './approvals'

const COUNTERS = ['confirmed', 'needs_clarification', 'pending_approval', 'rejected'] as const

export default function OverviewPage() {
  const { buyerId, account } = useAccount()
  const { events, live } = useEvents(buyerId)
  const view = useMemo(() => runView(events), [events])
  const runEvents = useMemo(() => latestRun(events), [events])
  const { data: orders } = usePoll<Order[]>(buyerId ? accountPath(buyerId, '/orders') : null, 4000)
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const o of orders ?? []) c[o.status] = (c[o.status] ?? 0) + 1
    return c
  }, [orders])
  const quoteLines = (view.quote?.lines ?? []) as unknown as QuoteLine[]

  return (
    <div className="space-y-5">
      {/* Scene / run header */}
      <Card className="gap-3 p-5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded bg-secondary px-2 py-0.5 font-semibold tracking-wide text-secondary-foreground uppercase">Pipeline</span>
          <span className="text-muted-foreground">{account?.name}</span>
          <span className="ml-auto">
            <LiveDot live={live} />
          </span>
        </div>
        <div>
          <h1 className="text-[22px] leading-tight font-semibold tracking-tight text-emphasis sm:text-[28px]">
            {view.scene?.title ?? 'What’s happening'}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground sm:text-base">
            {view.request ? `“${view.request}”` : view.scene?.subtitle ?? 'Waiting for the buyer agent to start.'}
          </p>
        </div>
      </Card>

      {/* Pipeline: AI agent → plain code → person */}
      <Card className="p-5 sm:p-6">
        <Stepper steps={view.steps} showWho />
      </Card>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        {/* Agent feed */}
        <Card className="h-[560px] gap-0 p-0">
          <CardHeader className="flex flex-row items-center gap-2 border-b py-3!">
            <Bot className="size-4 text-primary" aria-hidden />
            <CardTitle className="text-base">Agent feed</CardTitle>
            <Link to="/activity" className="ml-auto text-xs text-primary hover:underline">
              Full activity
            </Link>
          </CardHeader>
          <EventFeed events={runEvents} big className="flex-1" emptyText="No run yet for this account." />
        </Card>

        <div className="space-y-5">
          {/* Current quote / order */}
          <Card className="gap-3 p-5">
            <div className="flex items-center gap-2">
              <Receipt className="size-4 text-primary" aria-hidden />
              <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Order summary</span>
              {view.decision && <StatusBadge status={view.decision.status} className="ml-auto" />}
            </div>
            {view.quote ? (
              <>
                <div>
                  <div className="text-[32px] leading-none font-semibold tracking-tight text-emphasis tnum">{eur(view.quote.total_eur)}</div>
                  <div className="mt-1 text-xs text-muted-foreground tnum">
                    {view.quote.total_with_tax_eur != null && <>{eur(view.quote.total_with_tax_eur)} incl. VAT · </>}
                    {quoteLines.length} {quoteLines.length === 1 ? 'line' : 'lines'} · Valio Aimo
                  </div>
                </div>
                <ul className="space-y-2 rounded-lg border bg-muted/30 p-3">
                  {quoteLines.map((l) => (
                    <li key={l.product_id} className="text-sm">
                      <div className="leading-snug font-medium">{l.name}</div>
                      <div className="text-xs text-muted-foreground tnum">
                        {unitsBothWays(l)} · {eur(l.line_total_eur)} · arrives {shortDate(l.available_date)}
                      </div>
                      <LineTags line={l} />
                    </li>
                  ))}
                </ul>
                {view.decision?.order_id && (
                  <Link
                    to={`/orders/${view.decision.order_id}`}
                    className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                  >
                    Delivery progress <ArrowRight className="size-3.5" />
                  </Link>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No quote yet in this run.</p>
            )}
          </Card>

          {/* Approvals, phone-sized */}
          <Card className="gap-3 bg-muted/30 p-4">
            <div className="flex items-center gap-2">
              <ClipboardCheck className="size-4 text-primary" aria-hidden />
              <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Approve on your phone</span>
              <Link to="/approvals" className="ml-auto text-xs text-primary hover:underline">
                Open
              </Link>
            </div>
            <ApprovalList compact />
          </Card>
        </div>
      </div>

      {/* Outcome counters for this account */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {COUNTERS.map((s) => (
          <Link to="/orders" key={s}>
            <Card className="gap-2 p-4 transition-colors hover:border-primary/40">
              <StatusBadge status={s} />
              <div className="text-[26px] leading-none font-semibold text-emphasis tnum">{num(counts[s] ?? 0)}</div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
