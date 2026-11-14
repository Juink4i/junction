import { ArrowRight, CircleHelp, MessagesSquare, Package } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { ApprovalList } from '@/components/approval-list'
import { Empty, ErrorNote } from '@/components/common'
import { OrderRow } from '@/components/order-row'
import { Stepper } from '@/components/stepper'
import { StatusBadge } from '@/components/status'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccount } from '@/lib/account'
import { accountPath, useEvents, usePoll } from '@/lib/api'
import { eur } from '@/lib/format'
import { orderPhase, PHASES, runView, type Phase } from '@/lib/pipeline'
import { OrderFlow } from '@/components/order-flow'
import type { Order, PendingApproval } from '@/lib/types'
import { usePendingCount } from './use-pending'

function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-emphasis">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export default function ClientOverview() {
  const { account, buyerId } = useAccount()
  const pending = usePendingCount(buyerId)
  const { data: approvals } = usePoll<PendingApproval[]>(buyerId ? accountPath(buyerId, '/approvals') : null, 3000)
  const { data: orders, error, loading, reload } = usePoll<Order[]>(buyerId ? accountPath(buyerId, '/orders') : null, 4000)
  const { events } = useEvents(buyerId)
  const run = useMemo(() => runView(events), [events])
  const asking = (orders ?? []).filter((o) => o.status === 'needs_clarification')
  const m = account?.mandate
  const waiting = pending + asking.length
  const [phase, setPhase] = useState<Phase | null>(null)
  const counts = useMemo(() => {
    const c = Object.fromEntries(PHASES.map((p) => [p.key, 0])) as Record<Phase, number>
    for (const o of orders ?? []) c[orderPhase(o)] += 1
    return c
  }, [orders])
  const shown = (orders ?? []).filter((o) => !phase || orderPhase(o) === phase)

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-[24px] leading-tight font-semibold tracking-tight text-emphasis sm:text-[28px]">{account?.name ?? 'Your account'}</h1>
        {m && (
          <p className="mt-1 text-sm text-muted-foreground">
            Your agent orders on its own up to {eur(m.auto_approve.max_order_eur)} per order and {eur(m.auto_approve.max_line_eur)} per line.{' '}
            <Link to="/client/mandate" className="font-medium text-primary hover:underline">
              Change
            </Link>
          </p>
        )}
      </div>

      {/* Things only the buyer can decide */}
      {waiting > 0 && (
        <Section title={`Needs you · ${waiting}`}>
          {(approvals?.length ?? 0) > 0 && <ApprovalList buyerId={buyerId} hideEmpty />}
          {asking.map((o) => (
            <Card key={o.order_id} className="flex-row items-start gap-3 border-ask/30 bg-ask-soft/40 p-4">
              <CircleHelp className="mt-0.5 size-5 shrink-0 text-ask" aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <div className="font-medium">Your agent needs you to confirm an amount</div>
                <div className="text-muted-foreground">{o.question ?? o.reasons[0]}</div>
                <Link to="/client/chat" className="mt-1 inline-flex items-center gap-1 font-medium text-primary hover:underline">
                  See the conversation <ArrowRight className="size-3.5" />
                </Link>
              </div>
            </Card>
          ))}
        </Section>
      )}

      {/* The agent, right now */}
      <Section
        title="Right now"
        action={
          <Link to="/client/chat" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
            <MessagesSquare className="size-4" /> Open chat
          </Link>
        }
      >
        <Card className="gap-4 p-5">
          {run.runId || run.request ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">You asked:</span>
                <span className="text-sm font-medium">“{run.request ?? '…'}”</span>
                {run.decision && <StatusBadge status={run.decision.status} className="ml-auto" />}
              </div>
              <Stepper steps={run.steps} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Your agent is idle. Ask it for something in your ordering tool and it will show up here.</p>
          )}
        </Card>
      </Section>

      {/* Order flow: this account's orders by stage */}
      {orders && orders.length > 0 && (
        <Section title="Order flow">
          <Card className="p-5 sm:p-6">
            <OrderFlow counts={counts} selected={phase} onSelect={setPhase} />
          </Card>
        </Section>
      )}

      {/* Orders with delivery progress */}
      <Section
        title={phase ? `Your orders · ${PHASES.find((p) => p.key === phase)?.label}` : 'Your orders'}
        action={
          phase && (
            <button onClick={() => setPhase(null)} className="text-sm font-medium text-primary hover:underline">
              Show all
            </button>
          )
        }
      >
        <ErrorNote error={error} onRetry={reload} />
        {loading && !orders && <Skeleton className="h-28 w-full rounded-lg" />}
        {orders && orders.length === 0 && (
          <Empty icon={<Package className="size-6" />} title="No orders yet">
            When your agent places an order, you can follow its delivery here.
          </Empty>
        )}
        <div className="space-y-3">
          {shown.map((o) => (
            <OrderRow key={o.order_id} order={o} to={`/client/orders/${o.order_id}`} />
          ))}
        </div>
      </Section>
    </div>
  )
}
