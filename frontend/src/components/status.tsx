import { CheckCircle2, CircleHelp, Link2, Link2Off, OctagonX, Undo2, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { usePoll } from '@/lib/api'
import { statusLabel } from '@/lib/pipeline'
import type { VerifyResult } from '@/lib/types'
import { cn } from '@/lib/utils'

const STYLE: Record<string, { icon: typeof CheckCircle2; cls: string }> = {
  confirmed: { icon: CheckCircle2, cls: 'bg-ok-soft text-ok border-ok/25' },
  approved: { icon: CheckCircle2, cls: 'bg-ok-soft text-ok border-ok/25' },
  pending_approval: { icon: UserRound, cls: 'bg-wait-soft text-wait border-wait/25' },
  pending: { icon: UserRound, cls: 'bg-wait-soft text-wait border-wait/25' },
  rejected: { icon: OctagonX, cls: 'bg-stop-soft text-stop border-stop/25' },
  withdrawn: { icon: Undo2, cls: 'bg-muted text-muted-foreground border-border' },
}
const UNKNOWN = { icon: CircleHelp, cls: 'bg-muted text-muted-foreground border-border' }

/** The four outcomes, each with its own icon and label (never colour alone). */
export function StatusBadge({ status, size = 'sm', className }: { status: string; size?: 'sm' | 'lg'; className?: string }) {
  const s = STYLE[status] ?? UNKNOWN
  const Icon = s.icon
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium whitespace-nowrap',
        size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs',
        s.cls,
        className,
      )}
    >
      <Icon className={size === 'lg' ? 'size-4' : 'size-3.5'} aria-hidden />
      {statusLabel(status)}
    </span>
  )
}

/** Full-width banner with the server's decision and its reasons, verbatim. */
export function DecisionBanner({ status, reasons, children }: { status: string; reasons: string[]; children?: ReactNode }) {
  const s = STYLE[status] ?? UNKNOWN
  const Icon = s.icon
  return (
    <div className={cn('rounded-lg border p-3 sm:p-4', s.cls)} role="status">
      <div className="flex items-center gap-2 font-semibold">
        <Icon className="size-5 shrink-0" aria-hidden />
        {statusLabel(status)}
        <span className="ml-auto text-[11px] font-medium tracking-wide uppercase opacity-80">Server decision</span>
      </div>
      {reasons.length > 0 && (
        <ul className="mt-2 space-y-1 pl-7 text-sm text-foreground/90">
          {reasons.map((r, i) => (
            <li key={i} className="list-disc">
              {r}
            </li>
          ))}
        </ul>
      )}
      {children}
    </div>
  )
}

export function LiveDot({ live, label = 'Live' }: { live: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="relative flex size-2">
        {live && <span className="absolute inline-flex size-full animate-ping rounded-full bg-go opacity-60" />}
        <span className={cn('relative inline-flex size-2 rounded-full', live ? 'bg-go' : 'bg-muted-foreground/50')} />
      </span>
      {live ? label : 'Offline'}
    </span>
  )
}

/** Whole-chain check from /api/log/verify. Reveals nothing about other accounts. */
export function LogIntactBadge({ className }: { className?: string }) {
  const { data } = usePoll<VerifyResult>('/log/verify', 10000)
  if (!data) return null
  return data.ok ? (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border border-ok/25 bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok', className)}>
      <Link2 className="size-3.5" aria-hidden /> Log intact
    </span>
  ) : (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border border-stop/25 bg-stop-soft px-2 py-0.5 text-xs font-medium text-stop', className)}>
      <Link2Off className="size-3.5" aria-hidden /> Log broken at entry {data.broken_at_seq}
    </span>
  )
}
