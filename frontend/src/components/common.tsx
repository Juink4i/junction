import { AlertTriangle, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import type { ApiFailure } from '@/lib/api'
import { allergenName, eur, shortDate, tagName, unitsBothWays } from '@/lib/format'
import type { QuoteLine } from '@/lib/types'
import { cn } from '@/lib/utils'

export function PageHeader({ eyebrow, title, sub, actions }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">{eyebrow}</div>}
        <h1 className="text-[22px] leading-tight font-semibold tracking-tight text-emphasis sm:text-[26px]">{title}</h1>
        {sub && <p className="mt-1 text-sm text-muted-foreground">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function ErrorNote({ error, onRetry }: { error: ApiFailure | null; onRetry?: () => void }) {
  if (!error) return null
  return (
    <div className="flex items-start gap-3 rounded-lg border border-stop/25 bg-stop-soft p-3 text-sm text-stop" role="alert">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex-1 text-foreground/90">{error.message}</div>
      {error.retryable && onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RotateCw /> Retry
        </Button>
      )}
    </div>
  )
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 py-12 text-center">
      <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-go-soft text-go">{icon}</div>
      <div className="font-semibold text-emphasis">{title}</div>
      {children && <div className="mt-1 max-w-sm text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

export function Chip({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'sage' | 'warn' | 'stop' | 'ok'; className?: string }) {
  const tones = {
    neutral: 'bg-muted text-muted-foreground border-border',
    sage: 'bg-secondary text-secondary-foreground border-transparent',
    warn: 'bg-wait-soft text-wait border-wait/25',
    stop: 'bg-stop-soft text-stop border-stop/25',
    ok: 'bg-ok-soft text-ok border-ok/25',
  }
  return <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', tones[tone], className)}>{children}</span>
}

/** Stock is only ever "confirmed" or "unconfirmed"; raw numbers are never shown. */
export function LineTags({ line }: { line: QuoteLine }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      <Chip tone={line.stock === 'confirmed' ? 'ok' : 'neutral'}>stock {line.stock}</Chip>
      {line.cutoff_passed && <Chip tone="stop">cut-off passed</Chip>}
      {line.product?.allergen_info_missing && <Chip tone="warn">allergens unknown</Chip>}
    </span>
  )
}

export function LineSummary({ line }: { line: QuoteLine }) {
  return (
    <div className="space-y-1">
      <div className="text-sm font-medium text-foreground">{line.name}</div>
      <div className="text-xs text-muted-foreground tnum">
        {unitsBothWays(line)} · {eur(line.unit_price_eur)} per {line.sales_unit ? 'unit' : 'unit'} · arrives {shortDate(line.available_date)}
      </div>
      <LineTags line={line} />
    </div>
  )
}

export function AllergenChips({ codes, tone }: { codes: string[]; tone: 'stop' | 'warn' | 'ok' }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {codes.map((c) => (
        <Chip key={c} tone={tone}>
          {allergenName(c)}
        </Chip>
      ))}
    </span>
  )
}

export function TagChips({ tags }: { tags: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.map((t) => (
        <Chip key={t} tone="sage">
          {tagName(t)}
        </Chip>
      ))}
    </span>
  )
}
