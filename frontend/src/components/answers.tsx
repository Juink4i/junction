// Form widgets for a kitchen's answers, shared by onboarding and the mandate editor,
// so a field set at sign-up is edited later with the same control and the same choices.
import { ArrowUp, ChevronDown, Plus, Trash2, X } from 'lucide-react'
import { Popover } from 'radix-ui'
import { useState, type KeyboardEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Choice, OnboardingOptions, UsualOrder } from '@/lib/types'
import { cn, num, select } from '@/lib/utils'


/** Toggle chips. `single` makes them behave like radio buttons. */
export function Chips({ items, chosen, onChange, single, tone = 'sage' }: { items: Choice[]; chosen: string[]; onChange: (v: string[]) => void; single?: boolean; tone?: 'sage' | 'stop' }) {
  return (
    <div className="flex flex-wrap gap-2" role={single ? 'radiogroup' : 'group'}>
      {items.map((i) => {
        const on = chosen.includes(i.code)
        return (
          <button
            key={i.code}
            type="button"
            role={single ? 'radio' : undefined}
            aria-checked={single ? on : undefined}
            aria-pressed={single ? undefined : on}
            onClick={() => onChange(single ? [i.code] : on ? chosen.filter((c) => c !== i.code) : [...chosen, i.code])}
            className={cn(
              'min-h-9 rounded-full border px-3 text-[13px] font-medium transition-colors',
              on
                ? tone === 'stop'
                  ? 'border-stop/40 bg-stop-soft text-stop'
                  : 'border-primary bg-primary text-primary-foreground'
                : 'bg-white text-foreground hover:bg-muted',
            )}
          >
            {i.name}
          </button>
        )
      })}
    </div>
  )
}

/** Matches on the name first, then on the code or an example product, so "oat" finds "Plant-based drinks". */
export function findCategories(items: Choice[], query: string, skip: string[]): Choice[] {
  const q = query.trim().toLowerCase()
  const open = items.filter((c) => !skip.includes(c.code))
  if (!q) return open
  // From the start of a word, so "oat" does not find "goat" or "groats".
  const word = new RegExp(`(^|[^\\p{L}\\p{N}])${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'u')
  const inName = (c: Choice) => word.test(c.name.toLowerCase())
  const elsewhere = (c: Choice) => c.code.startsWith(q) || (c.examples ?? []).some((e) => word.test(e.toLowerCase()))
  return [...open.filter(inName), ...open.filter((c) => !inName(c) && elsewhere(c))]
}

/** A dropdown with a search box to add a category; what is picked shows as removable chips. */
export function CategoryPicker({ items, chosen, onChange }: { items: Choice[]; chosen: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const found = findCategories(items, query, chosen)
  const name = (code: string) => items.find((c) => c.code === code)?.name ?? code

  const show = (next: boolean) => {
    setOpen(next)
    setQuery('')
    setActive(0)
  }
  const pick = (code: string) => {
    onChange([...chosen, code])
    show(false)
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const next = Math.min(Math.max(active + (e.key === 'ArrowDown' ? 1 : -1), 0), found.length - 1)
      setActive(next)
      document.getElementById(`category-option-${next}`)?.scrollIntoView({ block: 'nearest' })
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (found[active]) pick(found[active].code)
    }
  }

  return (
    <div className="space-y-2">
      {chosen.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {chosen.map((code) => (
            <button
              key={code}
              type="button"
              aria-label={`Remove ${name(code)}`}
              onClick={() => onChange(chosen.filter((c) => c !== code))}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-primary bg-primary px-3 text-[13px] font-medium text-primary-foreground"
            >
              {name(code)} <X className="size-3.5" />
            </button>
          ))}
        </div>
      )}
      <Popover.Root open={open} onOpenChange={show}>
        <Popover.Trigger asChild>
          <button type="button" className={cn(select, 'flex w-full items-center justify-between text-left text-muted-foreground')}>
            {chosen.length ? 'Add another category' : 'Add a category'}
            <ChevronDown className="size-4" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={4}
            className="z-50 w-(--radix-popover-trigger-width) min-w-64 overflow-hidden rounded-md border bg-white shadow-md"
          >
            <div className="border-b p-2">
              <Input
                autoFocus
                type="search"
                placeholder="Search, for example butter or oat drink"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value)
                  setActive(0)
                }}
                onKeyDown={onKey}
                aria-label="Search categories"
              />
            </div>
            {found.length ? (
              <ul role="listbox" aria-label="Categories" className="max-h-64 overflow-y-auto py-1">
                {found.map((c, i) => (
                  <li key={c.code} id={`category-option-${i}`} role="option" aria-selected={i === active}>
                    <button
                      type="button"
                      onClick={() => pick(c.code)}
                      onMouseEnter={() => setActive(i)}
                      className={cn('w-full px-3 py-1.5 text-left', i === active && 'bg-muted')}
                    >
                      <span className="block text-sm font-medium text-emphasis">{c.name}</span>
                      {c.examples?.length ? <span className="block truncate text-xs text-muted-foreground">e.g. {c.examples.join(', ')}</span> : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-3 py-3 text-xs text-muted-foreground">No category matches “{query.trim()}”.</p>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  )
}

/**
 * Which day a usual order comes: a calendar of day squares (1–31) for a monthly order,
 * a row of weekday squares for a weekly one. Tap the chosen square again for "any day".
 */
export function DayPicker({
  label,
  every,
  value,
  weekdays,
  monthDays,
  onChange,
}: {
  label: string
  every: string
  value: string | number | null
  weekdays: Choice[]
  monthDays: number[]
  onChange: (v: string | number | null) => void
}) {
  const monthly = every === 'month'
  const square = (on: boolean) =>
    cn(
      'flex aspect-square min-w-0 items-center justify-center rounded-md border text-xs font-medium tnum transition-colors sm:text-[13px]',
      on ? 'border-go bg-go text-go-foreground shadow-[0_0_0_3px_var(--go-soft)]' : 'bg-white text-foreground hover:border-go/50 hover:bg-go-soft',
    )
  const said =
    value == null ? 'Any day' : monthly ? `On day ${value} of each month` : `Every ${weekdays.find((w) => w.code === value)?.name ?? value}`

  return (
    <fieldset className="space-y-2">
      <legend className="flex w-full items-center justify-between text-xs text-muted-foreground">
        <span>{monthly ? 'Which day of the month' : 'Which day of the week'}</span>
        <span className="font-medium text-emphasis">{said}</span>
      </legend>
      {monthly ? (
        <div className="grid grid-cols-7 gap-1" role="radiogroup" aria-label={`${label}: day of the month`}>
          {monthDays.map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={value === n}
              aria-label={`Day ${n}`}
              className={square(value === n)}
              onClick={() => onChange(value === n ? null : n)}
            >
              {n}
            </button>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-7 gap-1" role="radiogroup" aria-label={`${label}: day of the week`}>
          {weekdays.map((w) => (
            <button
              key={w.code}
              type="button"
              role="radio"
              aria-checked={value === w.code}
              aria-label={w.name}
              className={square(value === w.code)}
              onClick={() => onChange(value === w.code ? null : w.code)}
            >
              {w.name.slice(0, 3)}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={() => onChange(null)}
        aria-pressed={value == null}
        className={cn('rounded-full border px-2.5 py-0.5 text-xs font-medium', value == null ? 'border-primary bg-secondary text-secondary-foreground' : 'bg-white text-muted-foreground hover:bg-muted')}
      >
        Any day
      </button>
    </fieldset>
  )
}

/** The four priorities, most important first. "Up" swaps an item with the one above it. */
export function PriorityRanker({ codes, choices, onChange }: { codes: string[]; choices: Choice[]; onChange: (v: string[]) => void }) {
  const names = Object.fromEntries(choices.map((p) => [p.code, p.name]))
  return (
    <ol className="space-y-1">
      {codes.map((code, i) => (
        <li key={code} className="flex items-center gap-3 rounded-md border bg-white px-3 py-1.5">
          <span className="w-4 text-sm font-semibold text-muted-foreground tnum">{i + 1}</span>
          <span className="flex-1 text-sm">{names[code] ?? code}</span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={i === 0}
            aria-label={`Move ${names[code] ?? code} up`}
            onClick={() => {
              const next = [...codes]
              ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
              onChange(next)
            }}
          >
            <ArrowUp /> Up
          </Button>
        </li>
      ))}
    </ol>
  )
}

/** Usual orders: what, how much, how often, which day. `named` hides the name for a buyer with no profile to keep it in. */
export function UsualOrders({ orders, opts, onChange, named = true }: { orders: UsualOrder[]; opts: OnboardingOptions; onChange: (v: UsualOrder[]) => void; named?: boolean }) {
  const every = opts.periods.map((p) => ({ code: p.code, name: `every ${p.name}` }))
  const set = (i: number, change: Partial<UsualOrder>) => onChange(orders.map((o, j) => (j === i ? { ...o, ...change } : o)))

  return (
    <div className="space-y-3">
      {orders.map((o, i) => (
        <div key={i} className="space-y-2 rounded-md border bg-white p-3">
          <div className="flex gap-2">
            {named && <Input placeholder="What, for example milk" value={o.what} onChange={(e) => set(i, { what: e.target.value })} aria-label={`Usual order ${i + 1}: what`} />}
            <select className={cn(select, named ? 'max-w-44' : 'flex-1')} value={o.category} onChange={(e) => set(i, { category: e.target.value })} aria-label={`Usual order ${i + 1}: category`}>
              {opts.categories.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <Input
              className="w-24"
              type="number"
              min={0}
              inputMode="decimal"
              value={o.amount ?? ''}
              onChange={(e) => set(i, { amount: num(e.target.value) })}
              aria-label={`Usual order ${i + 1}: amount`}
            />
            <select className={select} value={o.unit} onChange={(e) => set(i, { unit: e.target.value as 'L' | 'KG' })} aria-label="Unit">
              <option value="L">L</option>
              <option value="KG">KG</option>
            </select>
            <select
              className={cn(select, 'flex-1')}
              value={o.every}
              // A weekday and a day of the month don't carry over.
              onChange={(e) => set(i, { every: e.target.value, on: null })}
              aria-label="How often"
            >
              {every.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name}
                </option>
              ))}
            </select>
            <Button type="button" variant="ghost" size="icon" aria-label={`Remove usual order ${i + 1}`} onClick={() => onChange(orders.filter((_, j) => j !== i))}>
              <Trash2 />
            </Button>
          </div>
          <DayPicker label={`Usual order ${i + 1}`} every={o.every} value={o.on ?? null} weekdays={opts.weekdays} monthDays={opts.month_days} onChange={(v) => set(i, { on: v })} />
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={() => onChange([...orders, { what: '', category: opts.categories[0].code, amount: null, unit: 'L', every: 'week' }])}>
        <Plus /> Add a usual order
      </Button>
    </div>
  )
}
