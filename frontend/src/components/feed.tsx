import { ArrowDown, Bot, Clapperboard, CornerDownRight, HelpCircle, Hourglass, Link2, Link2Off, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { eur, num, pct, shortDate, timeOf, unitsBothWays } from '@/lib/format'
import type { AgentEvent, Alternative, OptionCard } from '@/lib/types'
import { cn } from '@/lib/utils'
import { DecisionBanner } from './status'

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v)

const amountOf = (args: Obj) => (args.amount != null ? `${num(Number(args.amount))} ${args.unit ?? ''}`.trim() : null)

export function argsSummary(tool: string, args: Obj | undefined): string {
  if (!args) return ''
  if (tool === 'request_quote' && Array.isArray(args.product_ids)) {
    const n = args.product_ids.length
    return [`${n} ${n === 1 ? 'product' : 'products'}`, amountOf(args), args.need_by ? `by ${args.need_by}` : null]
      .filter(Boolean)
      .join(' · ')
  }
  if (tool === 'search_products') {
    const parts = [args.product ? `"${args.product}"` : null, ...((args.must_have as string[]) ?? []), amountOf(args)]
    return parts.filter(Boolean).join(' · ')
  }
  if (tool === 'place_order') return String(args.quote_id ?? '')
  return Object.entries(args)
    .filter(([k]) => k !== 'mandate_token' && k !== 'agent_signature')
    .map(([, v]) => (typeof v === 'object' ? JSON.stringify(v) : String(v)))
    .join(' · ')
    .slice(0, 120)
}

export function resultSummary(tool: string, result: unknown): string {
  if (isObj(result) && 'error' in result && isObj(result.error)) return String(result.error.message ?? 'error')
  if (isObj(result) && 'code' in result && 'message' in result) return String(result.message)
  if (Array.isArray(result)) return `${result.length} ${tool === 'search_products' ? 'products' : 'items'}`
  if (isObj(result)) {
    if (result.status === 'needs_clarification') return `asks: ${String(result.question ?? 'a question')}`
    if (Array.isArray(result.products)) {
      const dropped = Array.isArray(result.dropped) ? result.dropped.length : 0
      return `${result.products.length} products${dropped ? ` · ${dropped} left out` : ''}`
    }
    if (tool === 'request_quote' && Array.isArray(result.options)) {
      const n = result.options.length
      const best = isObj(result.options[0]) && isObj(result.options[0].quote) ? result.options[0].quote : null
      if (!best) return 'nothing could be offered'
      return `${n} signed ${n === 1 ? 'option' : 'options'} · best ${eur(Number(best.total_eur))}`
    }
    if (tool === 'get_product' && (result.name_en || result.name)) return String(result.name_en ?? result.name)
    if (result.status) return String(result.status)
  }
  return 'done'
}

function Bubble({ who, children, tone = 'agent' }: { who: string; children: React.ReactNode; tone?: 'agent' | 'buyer' }) {
  const Icon = tone === 'agent' ? Bot : UserRound
  return (
    <div className={cn('flex items-start gap-2.5', tone === 'buyer' && 'flex-row-reverse')}>
      <span
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-full border',
          tone === 'agent' ? 'bg-secondary text-secondary-foreground' : 'bg-card text-muted-foreground',
        )}
        aria-hidden
      >
        <Icon className="size-4" />
      </span>
      <div className={cn('min-w-0 max-w-[85%]', tone === 'buyer' && 'text-right')}>
        <div className="mb-0.5 text-xs font-medium text-muted-foreground">{who}</div>
        <div
          className={cn(
            'inline-block rounded-lg border px-3 py-2 text-left text-sm whitespace-pre-wrap',
            tone === 'agent' ? 'bg-card' : 'bg-primary text-primary-foreground border-transparent',
          )}
        >
          {children}
        </div>
      </div>
    </div>
  )
}

function Options({ title, options }: { title?: string; options: OptionCard[] }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 text-sm font-semibold text-emphasis">{title ?? 'Options'}</div>
      <div className="grid gap-2 md:grid-cols-3">
        {options.map((o, i) => (
          <div key={i} className={cn('rounded-md border p-2.5', i === 0 && 'border-go/50 bg-go-soft/50')}>
            <div className="mb-1 text-[11px] font-semibold tracking-wide text-go uppercase">{o.label}</div>
            <div className="text-sm leading-snug font-medium">{o.name}</div>
            <div className="mt-1 text-xs text-muted-foreground tnum">
              {unitsBothWays(o)}
              {o.total_eur != null && <> · {eur(o.total_eur)}</>}
              {o.available_date && <> · {shortDate(o.available_date)}</>}
            </div>
            {(o.delivery_reliability != null || o.carbon_kg_per_kg != null) && (
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {o.delivery_reliability != null && <>delivered in full {pct(o.delivery_reliability)}</>}
                {o.delivery_reliability != null && o.carbon_kg_per_kg != null && ' · '}
                {o.carbon_kg_per_kg != null && <>{num(o.carbon_kg_per_kg)} kg CO₂e/kg</>}
              </div>
            )}
            <div className="mt-1.5 text-xs text-foreground/80">{o.trade_off}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Other options from the same request that would go through without a person. */
export function Alternatives({ items }: { items?: Alternative[] }) {
  if (!items?.length) return null
  return (
    <div className="mt-2 rounded-md border border-go/25 bg-go-soft/40 p-2.5 text-sm text-foreground">
      <div className="mb-1 text-xs font-semibold text-go">Would go through without a person</div>
      <ul className="space-y-0.5">
        {items.map((a) => (
          <li key={a.quote_id} className="flex items-baseline gap-2">
            <span className="text-[11px] font-semibold tracking-wide text-go uppercase">{a.label}</span>
            <span className="min-w-0 flex-1">{a.summary}</span>
            <span className="font-medium tnum">{eur(a.total_eur)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function requestText(r: AgentEvent['request']): string {
  if (!r) return ''
  if (typeof r === 'string') return r
  const parts = [
    r.amount != null ? `${num(Number(r.amount))} ${r.unit ?? ''}` : null,
    r.product,
    r.need_by ? `by ${r.need_by}` : null,
    Array.isArray(r.must_have) && r.must_have.length ? `must be ${(r.must_have as string[]).join(', ')}` : null,
  ]
  return parts.filter(Boolean).join(' · ')
}

export function EventRow({ e, big }: { e: AgentEvent; big?: boolean }) {
  switch (e.kind) {
    case 'scene':
      return (
        <div className="flex items-center gap-3 pt-2">
          <Clapperboard className="size-4 text-primary" aria-hidden />
          <div>
            <div className="text-sm font-semibold text-emphasis">{e.title}</div>
            {e.subtitle && <div className="text-xs text-muted-foreground">{e.subtitle}</div>}
          </div>
          <span className="h-px flex-1 bg-border" />
        </div>
      )
    case 'run_start':
      return (
        <div className="text-xs text-muted-foreground">
          Agent started for <span className="font-medium text-foreground">{e.buyer_name}</span>
          {e.model ? ` · ${e.model}` : ''}
        </div>
      )
    case 'user':
      return <Bubble who="Buyer" tone="buyer">{e.text}</Bubble>
    case 'agent':
      return <Bubble who="Buyer agent">{e.text}</Bubble>
    case 'request':
      return (
        <div className="rounded-md border border-dashed bg-muted/40 px-3 py-2 text-xs">
          <span className="font-semibold text-emphasis">Understood request:</span> {requestText(e.request)}
        </div>
      )
    case 'tool_call':
      return (
        <div className={cn('font-mono text-xs break-words text-foreground/90', big && 'text-sm')}>
          <span className="font-semibold text-primary">→ {e.tool}</span>
          <span className="text-muted-foreground">(</span>
          {argsSummary(e.tool ?? '', e.args)}
          <span className="text-muted-foreground">)</span>
        </div>
      )
    case 'tool_result':
      return (
        <div className={cn('flex gap-1 pl-3 font-mono text-xs break-words', e.ok === false ? 'text-stop' : 'text-muted-foreground', big && 'text-sm')}>
          <CornerDownRight className="mt-0.5 size-3 shrink-0" aria-hidden />← {resultSummary(e.tool ?? '', e.result)}
        </div>
      )
    case 'options':
      return <Options title={e.title} options={e.options ?? []} />
    case 'ask':
      return (
        <div className="flex items-start gap-2 rounded-lg border border-ask/25 bg-ask-soft px-3 py-2 text-sm">
          <HelpCircle className="mt-0.5 size-4 shrink-0 text-ask" aria-hidden />
          <div>
            <div className="text-xs font-medium text-ask">Agent asks the buyer</div>
            {e.question}
          </div>
        </div>
      )
    case 'answer':
      return <Bubble who="Buyer" tone="buyer">{e.text}</Bubble>
    case 'waiting':
      return (
        <div className="flex items-center gap-2 text-sm text-wait">
          <Hourglass className="size-4 animate-pulse" aria-hidden /> Waiting for a person to approve…
        </div>
      )
    case 'decision': {
      const s = e.status ?? ''
      if (s === 'approved' || s === 'rejected' || s === 'pending') {
        const reasons = s === 'pending' ? ['Still waiting for a person.'] : [`${s === 'approved' ? 'Approved' : 'Rejected'} by ${e.decided_by ?? 'a person'}.`]
        return <DecisionBanner status={s === 'pending' ? 'pending_approval' : s === 'approved' ? 'confirmed' : 'rejected'} reasons={reasons} />
      }
      return (
        <DecisionBanner status={s} reasons={e.reasons ?? []}>
          <div className="pl-7">
            <Alternatives items={e.alternatives} />
          </div>
        </DecisionBanner>
      )
    }
    case 'run_end':
      return e.summary ? (
        <div className="rounded-md bg-muted/60 px-3 py-2 text-sm">
          <span className="font-semibold text-emphasis">Summary: </span>
          {e.summary}
        </div>
      ) : null
    case 'verify':
      return e.ok ? (
        <div className="flex items-center gap-2 rounded-lg border border-ok/25 bg-ok-soft px-3 py-2 text-sm font-medium text-ok">
          <Link2 className="size-4" aria-hidden /> Log intact{e.count ? `: all ${e.count} entries are chained` : ''}
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-stop/25 bg-stop-soft px-3 py-2 text-sm font-medium text-stop">
          <Link2Off className="size-4" aria-hidden /> Log broken at entry {e.broken_at_seq}
        </div>
      )
    case 'note':
      return <div className="text-xs text-muted-foreground italic">{e.text}</div>
    default:
      return null
  }
}

/** A run's summary is its agent's last message, which the feed already showed when it was said. */
export function repeatsAgent(e: AgentEvent, events: AgentEvent[]): boolean {
  return e.kind === 'run_end' && events.some((a) => a.kind === 'agent' && a.run_id === e.run_id && a.text === e.summary)
}

/** Auto-scrolling feed with a "jump to latest" pill when the reader scrolls up. */
export function EventFeed({ events, big, className, emptyText }: { events: AgentEvent[]; big?: boolean; className?: string; emptyText?: string }) {
  const box = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)

  useEffect(() => {
    if (pinned && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [events, pinned])

  const onScroll = () => {
    const el = box.current
    if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
  }

  return (
    <div className={cn('relative min-h-0', className)}>
      <div ref={box} onScroll={onScroll} className="h-full space-y-3 overflow-y-auto p-4" aria-live="polite">
        {events.length === 0 && <div className="py-10 text-center text-sm text-muted-foreground">{emptyText ?? 'Nothing yet.'}</div>}
        {events.filter((e) => !repeatsAgent(e, events)).map((e) => (
          <div key={e.id} className="animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
            <EventRow e={e} big={big} />
            {e.ts && e.kind !== 'scene' && e.kind !== 'tool_result' && (
              <div className="sr-only">{timeOf(e.ts)}</div>
            )}
          </div>
        ))}
      </div>
      {!pinned && (
        <Button size="sm" className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-md" onClick={() => setPinned(true)}>
          <ArrowDown /> Jump to latest
        </Button>
      )}
    </div>
  )
}
