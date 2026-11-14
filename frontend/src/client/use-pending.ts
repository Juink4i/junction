import { accountPath, usePoll } from '@/lib/api'
import type { PendingApproval } from '@/lib/types'

export function usePendingCount(buyerId: string | null): number {
  const { data } = usePoll<PendingApproval[]>(buyerId ? accountPath(buyerId, '/approvals') : null, 3000)
  return data?.length ?? 0
}
