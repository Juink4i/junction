import { ShieldCheck } from 'lucide-react'
import { ApprovalCard } from '@/components/approval-card'
import { Empty, ErrorNote, PageHeader } from '@/components/common'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccount } from '@/lib/account'
import { accountPath, usePoll } from '@/lib/api'
import type { PendingApproval } from '@/lib/types'

export function ApprovalList({ compact }: { compact?: boolean }) {
  const { buyerId } = useAccount()
  const { data, error, loading, reload } = usePoll<PendingApproval[]>(buyerId ? accountPath(buyerId, '/approvals') : null, 3000)
  if (loading && !data) return <Skeleton className="h-72 w-full rounded-lg" />
  return (
    <div className="space-y-3">
      <ErrorNote error={error} onRetry={reload} />
      {data && data.length === 0 && (
        <Empty icon={<ShieldCheck className="size-6" />} title="Nothing is waiting">
          {compact ? 'Your agent is within its limits.' : 'Your agent is within its limits. Orders that need a person will show up here.'}
        </Empty>
      )}
      {buyerId && data?.map((a) => <ApprovalCard key={a.approval_id} a={a} buyerId={buyerId} onDone={reload} />)}
    </div>
  )
}

export default function ApprovalsPage() {
  const { buyerId, account } = useAccount()
  const { data } = usePoll<PendingApproval[]>(buyerId ? accountPath(buyerId, '/approvals') : null, 3000)
  return (
    <div className="mx-auto max-w-md">
      <PageHeader
        eyebrow={account?.name}
        title={`Waiting for you · ${data?.length ?? 0}`}
        sub="Orders the server held because they are outside the signed mandate."
      />
      <ApprovalList />
    </div>
  )
}
