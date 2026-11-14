import { PHASES, type Phase } from '@/lib/pipeline'
import { cn } from '@/lib/utils'

const FLOW: Phase[] = ['awaiting_approval', 'approved', 'shipping', 'completed']
const SHORT: Record<Phase, string> = {
  awaiting_approval: 'Needs your approval',
  approved: 'Approved',
  shipping: 'Arriving today',
  completed: 'Delivered',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

/**
 * Orders by stage, as dots joined by a line with a count in each dot. Tapping a stage
 * selects it (tap again to clear). Delivery stages follow the promised delivery date.
 */
export function OrderFlow({
  counts,
  selected,
  onSelect,
}: {
  counts: Record<Phase, number>
  selected: Phase | null
  onSelect: (p: Phase | null) => void
}) {
  const pick = (p: Phase) => onSelect(selected === p ? null : p)
  return (
    <div className="space-y-4">
      <ol className="flex" aria-label="Your orders by stage">
        {FLOW.map((p, i) => {
          const n = counts[p]
          const wait = p === 'awaiting_approval'
          const meta = PHASES.find((x) => x.key === p)!
          return (
            <li key={p} className="relative flex min-w-0 flex-1 flex-col items-center text-center">
              {i > 0 && <span className="absolute top-[22px] right-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-go/70 sm:top-6 sm:h-1.5" aria-hidden />}
              <button
                type="button"
                onClick={() => pick(p)}
                aria-pressed={selected === p}
                title={meta.hint}
                className={cn(
                  'relative z-10 flex size-11 items-center justify-center rounded-full text-base font-semibold tnum transition-transform hover:scale-105 sm:size-12',
                  n === 0
                    ? 'border-2 border-border bg-white text-muted-foreground'
                    : wait
                      ? 'bg-wait-soft text-wait ring-2 ring-wait'
                      : 'bg-go text-go-foreground shadow-[0_0_0_4px_var(--go-soft)]',
                  selected === p && 'outline-2 outline-offset-4 outline-primary',
                )}
              >
                {n}
              </button>
              <div className={cn('mt-2 px-0.5 text-[11px] leading-tight font-semibold sm:text-sm', n ? 'text-emphasis' : 'text-muted-foreground')}>{SHORT[p]}</div>
            </li>
          )
        })}
      </ol>
      {counts.rejected > 0 && (
        <button
          type="button"
          onClick={() => pick('rejected')}
          aria-pressed={selected === 'rejected'}
          className={cn(
            'flex w-full items-center gap-2 rounded-lg border border-stop/25 bg-stop-soft/50 px-3 py-2 text-left text-sm',
            selected === 'rejected' && 'ring-2 ring-stop/40',
          )}
        >
          <span className="flex size-6 items-center justify-center rounded-full bg-stop text-xs font-semibold text-white tnum">{counts.rejected}</span>
          <span className="font-medium text-stop">Rejected</span>
          <span className="text-muted-foreground">· a rule was broken or you said no</span>
        </button>
      )}
      {counts.withdrawn > 0 && (
        <button
          type="button"
          onClick={() => pick('withdrawn')}
          aria-pressed={selected === 'withdrawn'}
          className={cn(
            'flex w-full items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-left text-sm',
            selected === 'withdrawn' && 'ring-2 ring-border',
          )}
        >
          <span className="flex size-6 items-center justify-center rounded-full bg-muted-foreground text-xs font-semibold text-white tnum">{counts.withdrawn}</span>
          <span className="font-medium">Withdrawn</span>
          <span className="text-muted-foreground">· replaced by another option from the same request</span>
        </button>
      )}
      <p className="text-xs text-muted-foreground">Delivery stages follow Valio Aimo’s promised delivery date.</p>
    </div>
  )
}
