import { ShieldCheck } from 'lucide-react'
import { ApprovalCard } from '@/components/approval-card'
import { Empty, ErrorNote } from '@/components/common'
import { Skeleton } from '@/components/ui/skeleton'
import { accountPath, usePoll } from '@/lib/api'
import type { PendingApproval } from '@/lib/types'

/** This account's pending approvals (polled every 3 s), each with Approve / Reject. */
export function ApprovalList({ buyerId, hideEmpty }: { buyerId: string | null; hideEmpty?: boolean }) {
  const { data, error, loading, reload } = usePoll<PendingApproval[]>(buyerId ? accountPath(buyerId, '/approvals') : null, 3000)
  if (loading && !data) return <Skeleton className="h-40 w-full rounded-lg" />
  return (
    <div className="space-y-3">
      <ErrorNote error={error} onRetry={reload} />
      {data && data.length === 0 && !hideEmpty && (
        <Empty icon={<ShieldCheck className="size-6" />} title="Nothing is waiting for you">
          Your agent is within its limits.
        </Empty>
      )}
      {buyerId && data?.map((a) => <ApprovalCard key={a.approval_id} a={a} buyerId={buyerId} onDone={reload} />)}
    </div>
  )
}
