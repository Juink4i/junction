import { Check, Loader2, Quote, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { accountPath, api, type ApiFailure } from '@/lib/api'
import { ago, eur, shortDate } from '@/lib/format'
import type { PendingApproval } from '@/lib/types'
import { LineTags } from './common'
import { unitsBothWays } from '@/lib/format'

/** One pending approval: what, how much, why it needs a person, and Approve / Reject. */
export function ApprovalCard({ a, buyerId, onDone }: { a: PendingApproval; buyerId: string; onDone: () => void }) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [confirmReject, setConfirmReject] = useState(false)
  const delivery = a.lines.map((l) => l.available_date).filter(Boolean).sort().at(-1) ?? null

  const decide = async (action: 'approve' | 'reject') => {
    setBusy(action)
    try {
      await api(accountPath(buyerId, `/approvals/${a.approval_id}/${action}`), { method: 'POST', body: '{}' })
      toast.success(action === 'approve' ? 'Approved. The agent has been told.' : 'Rejected. The agent has been told and won’t retry.')
      onDone()
    } catch (e) {
      toast.error((e as ApiFailure).message)
    } finally {
      setBusy(null)
      setConfirmReject(false)
    }
  }

  return (
    <Card className="gap-0 overflow-hidden p-0">
      <div className="p-4">
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="truncate">{a.buyer}</span>
          <span className="shrink-0">{ago(a.created_at)}</span>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-[28px] leading-none font-semibold tracking-tight text-emphasis tnum">{eur(a.total_eur)}</span>
        </div>
        <div className="mt-1 text-xs text-muted-foreground tnum">{eur(a.total_with_tax_eur)} incl. VAT</div>

        <ul className="mt-3 space-y-2.5">
          {a.lines.map((l) => (
            <li key={l.product_id} className="text-sm">
              <div className="font-medium">
                <span className="tnum">{unitsBothWays(l)}</span> {l.name}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <span>Arrives {shortDate(l.available_date ?? delivery)}</span>
                <LineTags line={l} />
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-4 rounded-lg border border-wait/25 bg-wait-soft p-3">
          <div className="mb-1 text-xs font-semibold tracking-wide text-wait uppercase">Why it needs you</div>
          <ul className="space-y-1 pl-4 text-sm">
            {a.reasons.map((r, i) => (
              <li key={i} className="list-disc">
                {r}
              </li>
            ))}
          </ul>
        </div>

        {a.agent_rationale && (
          <div className="mt-3 flex gap-2 text-sm text-muted-foreground">
            <Quote className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              <span className="font-medium text-foreground/80">Agent’s reason: </span>“{a.agent_rationale}”
            </span>
          </div>
        )}
        <div className="mt-2 text-[11px] text-muted-foreground">Approver: {a.approvers.join(', ') || 'named in the mandate'}</div>
      </div>
      <div className="grid grid-cols-2 gap-2 border-t bg-muted/30 p-3">
        <Button
          variant="outline"
          className="h-11 border-stop/40 text-stop hover:bg-stop-soft hover:text-stop"
          disabled={!!busy}
          onClick={() => setConfirmReject(true)}
        >
          {busy === 'reject' ? <Loader2 className="animate-spin" /> : <X />} Reject
        </Button>
        <Button className="h-11" disabled={!!busy} onClick={() => decide('approve')}>
          {busy === 'approve' ? <Loader2 className="animate-spin" /> : <Check />} Approve
        </Button>
      </div>

      <Sheet open={confirmReject} onOpenChange={setConfirmReject}>
        <SheetContent side="bottom" className="mx-auto max-w-md rounded-t-xl">
          <SheetHeader>
            <SheetTitle>Reject this order?</SheetTitle>
            <SheetDescription>
              {eur(a.total_eur)} for {a.buyer}. The agent will be told and won’t retry. This can’t be undone.
            </SheetDescription>
          </SheetHeader>
          <SheetFooter className="grid grid-cols-2 gap-2">
            <Button variant="outline" className="h-11" onClick={() => setConfirmReject(false)}>
              Keep it
            </Button>
            <Button variant="destructive" className="h-11" disabled={!!busy} onClick={() => decide('reject')}>
              {busy === 'reject' ? <Loader2 className="animate-spin" /> : <X />} Reject order
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </Card>
  )
}
