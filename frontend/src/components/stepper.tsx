import {
  Bot,
  Check,
  ClipboardCheck,
  House,
  PackageOpen,
  Code2,
  FileSignature,
  ListChecks,
  Minus,
  PackageCheck,
  Scale,
  Search,
  Truck,
  UserCheck,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react'
import { timeOf } from '@/lib/format'
import type { Step } from '@/lib/pipeline'
import { cn } from '@/lib/utils'

const ICONS: Record<string, LucideIcon> = {
  shop: Search,
  compare: ListChecks,
  rules: Scale,
  person: UserRound,
  quoted: FileSignature,
  approval: UserCheck,
  confirmed: PackageCheck,
  delivery: Truck,
  confirming: ClipboardCheck,
  preparing: PackageOpen,
  out: Truck,
  delivered: House,
}

const WHO: Record<Step['who'], { label: string; icon: LucideIcon }> = {
  agent: { label: 'AI agent', icon: Bot },
  code: { label: 'Plain code', icon: Code2 },
  person: { label: 'Person', icon: UserRound },
  valio: { label: 'Valio Aimo', icon: PackageCheck },
}

const STATE_TEXT: Record<Step['state'], string> = {
  done: 'Done',
  active: 'In progress',
  todo: 'Next',
  skipped: 'Not needed',
  stopped: 'Stopped',
}

// A delivery that is under way is "scheduled": there is no live tracking to say more.
// After a stop, later steps are "not reached" rather than "next".
const stateText = (s: Step, halted = false) =>
  s.key === 'delivery' && s.state === 'active' ? 'Scheduled' : halted && s.state === 'todo' ? 'Not reached' : STATE_TEXT[s.state]

/** A green dot: filled when done, ringed and pulsing while in progress, red when stopped. */
function Dot({ step }: { step: Step }) {
  const Icon = step.state === 'stopped' ? X : step.state === 'skipped' ? Minus : (ICONS[step.key] ?? Check)
  return (
    <span
      className={cn(
        'relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full transition-colors sm:size-12',
        step.state === 'done' && 'bg-go text-go-foreground shadow-[0_0_0_4px_var(--go-soft)]',
        step.state === 'active' && 'bg-go-soft text-go ring-2 ring-go',
        step.state === 'todo' && 'border-2 border-border bg-card text-muted-foreground',
        step.state === 'skipped' && 'border-2 border-dashed border-go/40 bg-card text-go/70',
        step.state === 'stopped' && 'bg-stop text-white shadow-[0_0_0_4px_var(--stop-soft)]',
      )}
      aria-hidden
    >
      {step.state === 'active' && <span className="absolute inset-0 animate-ping rounded-full bg-go/25" />}
      <Icon className="size-4 sm:size-5" strokeWidth={2.25} />
    </span>
  )
}

/** The line between two dots: solid green once the journey has passed it. */
function lineClass(from: Step, to: Step): string {
  if (from.state === 'stopped' || to.state === 'stopped') return 'bg-stop/40'
  const passed = (s: Step) => s.state === 'done' || s.state === 'skipped'
  if (passed(from) && passed(to)) return 'bg-go'
  if (passed(from) && to.state === 'active') return 'bg-gradient-to-r from-go via-go to-go/30'
  return 'bg-border'
}

/**
 * Dots joined by a line, as a progress indicator. Horizontal at every width (the phone
 * keeps the same line of dots; the detail lines show from `sm` up).
 * `detailFor` lets a page replace a step's detail line (e.g. a formatted delivery date).
 */
export function Stepper({ steps, detailFor, showWho }: { steps: Step[]; detailFor?: (s: Step) => string | null; showWho?: boolean }) {
  const halted = steps.some((s) => s.state === 'stopped')
  return (
    <ol className="flex" aria-label="Progress">
      {steps.map((s, i) => (
        <li
          key={s.key}
          className="relative flex min-w-0 flex-1 flex-col items-center text-center"
          aria-current={s.state === 'active' ? 'step' : undefined}
        >
          {i > 0 && (
            <span
              className={cn(
                'absolute top-[18px] right-1/2 h-1 w-full -translate-y-1/2 rounded-full sm:top-6 sm:h-1.5',
                lineClass(steps[i - 1], s),
              )}
              aria-hidden
            />
          )}
          <Dot step={s} />
          <div className="mt-2 w-full px-0.5 sm:mt-3 sm:px-1">
            <div
              className={cn(
                'text-[11px] leading-tight font-semibold break-words sm:text-sm',
                s.state === 'todo' ? 'text-muted-foreground' : 'text-emphasis',
              )}
            >
              {s.title}
            </div>
            <div
              className={cn(
                'text-[10px] font-medium tracking-wide uppercase sm:text-[11px]',
                s.state === 'done' || s.state === 'active' || s.state === 'skipped'
                  ? 'text-go'
                  : s.state === 'stopped'
                    ? 'text-stop'
                    : 'text-muted-foreground',
              )}
            >
              {stateText(s, halted)}
              {s.time ? <span className="hidden sm:inline"> · {timeOf(s.time).slice(0, 5)}</span> : null}
            </div>
            <div className="mx-auto mt-1 hidden max-w-[20ch] text-xs text-muted-foreground sm:block">{detailFor?.(s) ?? s.detail}</div>
            {showWho && <WhoTag who={s.who} />}
          </div>
          <span className="sr-only">
            {s.title}: {stateText(s, halted)}. {detailFor?.(s) ?? s.detail}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** Step details as a list, for phones where the dots have no room for them. */
export function StepDetails({ steps, detailFor }: { steps: Step[]; detailFor?: (s: Step) => string | null }) {
  return (
    <ul className="mt-4 space-y-1.5 border-t pt-3 sm:hidden">
      {steps.map((s) => (
        <li key={s.key} className="flex gap-2 text-xs">
          <span
            className={cn(
              'mt-1 size-2 shrink-0 rounded-full',
              s.state === 'done' || s.state === 'skipped' ? 'bg-go' : s.state === 'active' ? 'bg-go ring-2 ring-go-soft' : s.state === 'stopped' ? 'bg-stop' : 'bg-border',
            )}
            aria-hidden
          />
          <span>
            <span className="font-medium text-emphasis">{s.title}:</span>{' '}
            <span className="text-muted-foreground">{detailFor?.(s) ?? s.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function WhoTag({ who }: { who: Step['who'] }) {
  const w = WHO[who]
  const Icon = w.icon
  return (
    <span
      className={cn(
        'mt-1.5 hidden items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium sm:inline-flex',
        who === 'code' ? 'bg-emphasis text-background' : 'bg-muted text-muted-foreground',
      )}
    >
      <Icon className="size-3" aria-hidden /> {w.label}
    </span>
  )
}
