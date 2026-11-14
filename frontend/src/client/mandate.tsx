import { AlertTriangle, BadgeCheck, Ban, CalendarClock, Euro, Loader2, Pencil, Repeat, ShieldAlert, Tags, UserCheck, Wallet } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { AllergenChips, Chip, TagChips } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useAccount } from '@/lib/account'
import { accountPath, api, type ApiFailure } from '@/lib/api'
import { allergenName, categoryName, eur, shortDate, tagName } from '@/lib/format'
import type { Account, Mandate, MandateChanges } from '@/lib/types'
import { cn } from '@/lib/utils'

// Choices offered in the editor. The server validates every value again.
const TAG_CHOICES = ['FREE_FROM_LACTOSE', 'FREE_FROM_GLUTEN', 'VEGAN', 'VEGETARIAN', 'FREE_FROM_EGGS', 'FREE_FROM_SOY', 'LOW_LACTOSE']
const WEEKDAYS: Record<string, string> = { MON: 'Monday', TUE: 'Tuesday', WED: 'Wednesday', THU: 'Thursday', FRI: 'Friday', SAT: 'Saturday', SUN: 'Sunday' }
const ALLERGEN_CHOICES =['AM', 'ML', 'AW', 'AE', 'AY', 'AF', 'AC', 'UM', 'AP', 'AN', 'AS', 'AU', 'BC', 'BM', 'NL']

function Rule({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3 py-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary text-secondary-foreground">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-emphasis">{title}</div>
        <div className="text-sm text-muted-foreground">{children}</div>
      </div>
    </li>
  )
}

function Rules({ m }: { m: Mandate }) {
  return (
    <ul className="divide-y">
      <Rule icon={<Euro className="size-4" />} title="Orders on its own up to">
        {eur(m.auto_approve.max_order_eur)} per order
        {m.auto_approve.max_line_eur != null && <> and {eur(m.auto_approve.max_line_eur)} per line</>}. Above that, you approve.
      </Rule>
      <Rule icon={<Wallet className="size-4" />} title="Budget">
        {m.budget ? `${eur(m.budget.max_eur)} per ${m.budget.period}. Going over comes to you.` : 'No budget limit.'}
      </Rule>
      <Rule icon={<Tags className="size-4" />} title="Allowed categories">
        {m.auto_approve.allowed_categories?.length ? m.auto_approve.allowed_categories.map(categoryName).join(', ') : 'Any category.'}
      </Rule>
      <Rule icon={<Repeat className="size-4" />} title="Substitutes">
        {m.substitution.allowed ? (
          <span className="inline-flex flex-wrap items-center gap-1">
            Allowed, at most {m.substitution.max_price_increase_pct}% more per litre
            {m.substitution.must_keep.length > 0 && (
              <>
                , and must stay <TagChips tags={m.substitution.must_keep} />
              </>
            )}
          </span>
        ) : (
          'Not allowed.'
        )}
      </Rule>
      <Rule icon={<Ban className="size-4" />} title="Never buy (allergens)">
        {m.hard_rules.blocked_allergens.length ? <AllergenChips codes={m.hard_rules.blocked_allergens} tone="stop" /> : 'Nothing blocked.'}
      </Rule>
      <Rule icon={<ShieldAlert className="size-4" />} title="When allergen info is missing">
        {m.hard_rules.unknown_allergens === 'reject' ? 'Don’t buy it.' : m.hard_rules.unknown_allergens === 'human' ? 'Ask you first. Unknown is never treated as safe.' : 'Buy it anyway.'}
      </Rule>
      <Rule icon={<CalendarClock className="size-4" />} title="Delivery">
        {m.delivery?.days?.length ? `Only on ${m.delivery.days.map((d) => WEEKDAYS[d] ?? d).join(', ')}. ` : 'Any day. '}
        Must arrive by the date you need it. Another day, or a missed order cut-off, comes to you.
      </Rule>
      {m.usual_orders && m.usual_orders.length > 0 && (
        <Rule icon={<Repeat className="size-4" />} title="Usual orders">
          <ul className="space-y-0.5">
            {m.usual_orders.map((o, i) => (
              <li key={i}>
                {o.amount} {o.content_unit} of {categoryName(o.category)} every {o.every}
                {o.on != null && (o.every === 'month' ? ` on day ${o.on}` : ` on ${WEEKDAYS[String(o.on)] ?? o.on}`)}
              </li>
            ))}
          </ul>
          <span className="text-xs">An order more than 5 times the usual is checked with you first.</span>
        </Rule>
      )}
      <Rule icon={<UserCheck className="size-4" />} title="Who approves">
        {m.approvers.join(', ')}
      </Rule>
    </ul>
  )
}

interface Draft {
  maxOrder: string
  maxLine: string
  anyCategory: boolean
  categories: string
  subsAllowed: boolean
  subsPct: string
  mustKeep: string[]
  blocked: string[]
  unknown: string
  approvers: string
  validUntil: string
  budget: string
  budgetPeriod: string
  days: string[]
}

const draftOf = (m: Mandate): Draft => ({
  maxOrder: String(m.auto_approve.max_order_eur ?? ''),
  maxLine: String(m.auto_approve.max_line_eur ?? ''),
  anyCategory: !m.auto_approve.allowed_categories?.length,
  categories: (m.auto_approve.allowed_categories ?? []).join(', '),
  subsAllowed: m.substitution.allowed,
  subsPct: String(m.substitution.max_price_increase_pct),
  mustKeep: m.substitution.must_keep,
  blocked: m.hard_rules.blocked_allergens,
  unknown: m.hard_rules.unknown_allergens === 'reject' ? 'reject' : 'human',
  approvers: m.approvers.join(', '),
  validUntil: m.valid_until,
  budget: m.budget ? String(m.budget.max_eur) : '',
  budgetPeriod: m.budget?.period ?? 'week',
  days: m.delivery?.days ?? [],
})

const list = (s: string) => s.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean)

function changesOf(m: Mandate, d: Draft): { body: MandateChanges; summary: string[] } {
  const body: MandateChanges = {}
  const summary: string[] = []
  const auto: NonNullable<MandateChanges['auto_approve']> = {}
  if (Number(d.maxOrder) !== m.auto_approve.max_order_eur) {
    auto.max_order_eur = Number(d.maxOrder)
    summary.push(`Per order: ${eur(m.auto_approve.max_order_eur)} → ${eur(Number(d.maxOrder))}`)
  }
  if (d.maxLine !== '' && Number(d.maxLine) !== m.auto_approve.max_line_eur) {
    auto.max_line_eur = Number(d.maxLine)
    summary.push(`Per line: ${m.auto_approve.max_line_eur == null ? 'no limit' : eur(m.auto_approve.max_line_eur)} → ${eur(Number(d.maxLine))}`)
  }
  const cats = d.anyCategory ? [] : list(d.categories)
  if (cats.join() !== (m.auto_approve.allowed_categories ?? []).join()) {
    auto.allowed_categories = cats.length ? cats : null
    summary.push(`Categories: ${cats.length ? cats.join(', ') : 'any'}`)
  }
  if (Object.keys(auto).length) body.auto_approve = auto

  const subs: NonNullable<MandateChanges['substitution']> = {}
  if (d.subsAllowed !== m.substitution.allowed) {
    subs.allowed = d.subsAllowed
    summary.push(`Substitutes: ${d.subsAllowed ? 'allowed' : 'not allowed'}`)
  }
  if (Number(d.subsPct) !== m.substitution.max_price_increase_pct) {
    subs.max_price_increase_pct = Number(d.subsPct)
    summary.push(`Substitutes may cost up to ${d.subsPct}% more`)
  }
  if (d.mustKeep.join() !== m.substitution.must_keep.join()) {
    subs.must_keep = d.mustKeep
    summary.push(`Substitutes must stay: ${d.mustKeep.map(tagName).join(', ') || 'nothing in particular'}`)
  }
  if (Object.keys(subs).length) body.substitution = subs

  const hard: NonNullable<MandateChanges['hard_rules']> = {}
  if (d.blocked.join() !== m.hard_rules.blocked_allergens.join()) {
    hard.blocked_allergens = d.blocked
    summary.push(`Never buy: ${d.blocked.map(allergenName).join(', ') || 'nothing blocked'}`)
  }
  if (d.unknown !== m.hard_rules.unknown_allergens) {
    hard.unknown_allergens = d.unknown
    summary.push(`Missing allergen info: ${d.unknown === 'reject' ? 'don’t buy' : 'ask first'}`)
  }
  if (Object.keys(hard).length) body.hard_rules = hard

  const budget = d.budget === '' ? null : { period: d.budgetPeriod, max_eur: Number(d.budget) }
  if (JSON.stringify(budget) !== JSON.stringify(m.budget ? { period: m.budget.period, max_eur: m.budget.max_eur } : null)) {
    body.budget = budget
    summary.push(`Budget: ${budget ? `${eur(budget.max_eur)} per ${budget.period}` : 'none'}`)
  }
  const order = Object.keys(WEEKDAYS)
  const days = [...d.days].sort((x, y) => order.indexOf(x) - order.indexOf(y))
  if (days.join() !== (m.delivery?.days ?? []).join()) {
    body.delivery = { days }
    summary.push(`Delivery days: ${days.length ? days.map((x) => WEEKDAYS[x]).join(', ') : 'any day'}`)
  }
  if (list(d.approvers).join() !== m.approvers.join()) {
    body.approvers = list(d.approvers)
    summary.push(`Approvers: ${list(d.approvers).join(', ')}`)
  }
  if (d.validUntil !== m.valid_until) {
    body.valid_until = d.validUntil
    summary.push(`Valid until ${shortDate(d.validUntil)}`)
  }
  return { body, summary }
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-emphasis">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}

function Toggle({ on, onClick, children, tone = 'sage' }: { on: boolean; onClick: () => void; children: ReactNode; tone?: 'sage' | 'stop' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={cn(
        'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
        on ? (tone === 'stop' ? 'border-stop/40 bg-stop-soft text-stop' : 'border-primary bg-secondary text-secondary-foreground') : 'bg-white text-muted-foreground hover:bg-muted',
      )}
    >
      {children}
    </button>
  )
}

function Editor({ account, m, onDone }: { account: Account; m: Mandate; onDone: () => void }) {
  const [d, setD] = useState<Draft>(() => draftOf(m))
  const [confirm, setConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const toggle = (k: 'mustKeep' | 'blocked' | 'days', v: string) =>
    setD((x) => ({ ...x, [k]: x[k].includes(v) ? x[k].filter((y) => y !== v) : [...x[k], v] }))
  const { body, summary } = changesOf(m, d)

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await api(accountPath(account.buyer_id, '/mandate'), { method: 'PUT', body: JSON.stringify(body) })
      toast.success('Signed and saved. Your agent uses the new rules from its next order.')
      onDone()
    } catch (e) {
      setError((e as ApiFailure).message)
      setConfirm(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault()
        setConfirm(true)
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Most per order (€)" hint="Bigger orders come to you for approval.">
          <Input type="number" min={1} step="any" inputMode="decimal" value={d.maxOrder} onChange={(e) => set('maxOrder', e.target.value)} required />
        </Field>
        <Field label="Most per line (€)" hint={m.auto_approve.max_line_eur == null ? 'Optional.' : undefined}>
          <Input type="number" min={1} step="any" inputMode="decimal" value={d.maxLine} onChange={(e) => set('maxLine', e.target.value)} required={m.auto_approve.max_line_eur != null} />
        </Field>
      </div>

      <Field label="Budget (€)" hint="Leave empty for no budget. It cannot be less than the most per order.">
        <div className="flex max-w-sm gap-2">
          <Input type="number" min={1} step="any" inputMode="decimal" value={d.budget} onChange={(e) => set('budget', e.target.value)} />
          <select className="h-9 rounded-md border bg-white px-2 text-sm" value={d.budgetPeriod} onChange={(e) => set('budgetPeriod', e.target.value)} disabled={d.budget === ''} aria-label="Budget period">
            <option value="week">per week</option>
            <option value="month">per month</option>
          </select>
        </div>
      </Field>

      <div className="space-y-1.5">
        <span className="text-sm font-medium text-emphasis">Days you can receive goods</span>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(WEEKDAYS).map(([code, name]) => (
            <Toggle key={code} on={d.days.includes(code)} onClick={() => toggle('days', code)}>
              {name}
            </Toggle>
          ))}
        </div>
        <span className="block text-xs text-muted-foreground">None picked means any day.</span>
      </div>

      <Field label="Categories" hint="Category codes from the Valio Aimo product file, e.g. 10400 = milk and sour milk.">
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-[var(--primary)]" checked={d.anyCategory} onChange={(e) => set('anyCategory', e.target.checked)} />
            Any category
          </label>
          {!d.anyCategory && <Input className="max-w-xs" value={d.categories} onChange={(e) => set('categories', e.target.value)} placeholder="10400" />}
        </div>
      </Field>

      <div className="space-y-3 rounded-lg border p-4">
        <label className="flex items-center gap-2 text-sm font-medium text-emphasis">
          <input type="checkbox" className="accent-[var(--primary)]" checked={d.subsAllowed} onChange={(e) => set('subsAllowed', e.target.checked)} />
          Allow substitutes when something runs out
        </label>
        {d.subsAllowed && (
          <>
            <Field label="May cost up to (% more per litre)">
              <Input className="max-w-32" type="number" min={0} max={100} value={d.subsPct} onChange={(e) => set('subsPct', e.target.value)} />
            </Field>
            <div className="space-y-1.5">
              <span className="text-sm font-medium text-emphasis">A substitute must still be</span>
              <div className="flex flex-wrap gap-1.5">
                {TAG_CHOICES.map((t) => (
                  <Toggle key={t} on={d.mustKeep.includes(t)} onClick={() => toggle('mustKeep', t)}>
                    {tagName(t)}
                  </Toggle>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      <div className="space-y-1.5">
        <span className="text-sm font-medium text-emphasis">Never buy anything containing</span>
        <div className="flex flex-wrap gap-1.5">
          {ALLERGEN_CHOICES.map((a) => (
            <Toggle key={a} tone="stop" on={d.blocked.includes(a)} onClick={() => toggle('blocked', a)}>
              {allergenName(a)}
            </Toggle>
          ))}
        </div>
      </div>

      <Field label="When allergen info is missing" hint="Unknown is never treated as safe.">
        <select
          className="h-9 w-full max-w-xs rounded-md border bg-white px-3 text-sm"
          value={d.unknown}
          onChange={(e) => set('unknown', e.target.value)}
        >
          <option value="human">Ask me first</option>
          <option value="reject">Don’t buy it</option>
        </select>
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Who approves" hint="Email addresses, separated by commas.">
          <Input value={d.approvers} onChange={(e) => set('approvers', e.target.value)} required />
        </Field>
        <Field label="Valid until">
          <Input type="date" value={d.validUntil} onChange={(e) => set('validUntil', e.target.value)} required />
        </Field>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-stop/25 bg-stop-soft p-3 text-sm text-stop" role="alert">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> <span className="text-foreground/90">{error}</span>
        </div>
      )}

      <div className="flex gap-2">
        <Button type="button" variant="outline" className="h-10" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" className="h-10" disabled={summary.length === 0}>
          Review and sign
        </Button>
      </div>

      <Sheet open={confirm} onOpenChange={setConfirm}>
        <SheetContent side="bottom" className="mx-auto max-w-lg rounded-t-xl">
          <SheetHeader>
            <SheetTitle>Sign the new rules?</SheetTitle>
            <SheetDescription>Your mandate is signed again with your key. Valio Aimo’s server enforces it from your agent’s next order, and the change is written to the audit log.</SheetDescription>
          </SheetHeader>
          <ul className="space-y-1 px-4 text-sm">
            {summary.map((s) => (
              <li key={s} className="list-inside list-disc">
                {s}
              </li>
            ))}
          </ul>
          <SheetFooter className="grid grid-cols-2 gap-2">
            <Button variant="outline" className="h-11" onClick={() => setConfirm(false)}>
              Back
            </Button>
            <Button className="h-11" disabled={saving} onClick={save}>
              {saving ? <Loader2 className="animate-spin" /> : <BadgeCheck />} Sign and save
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </form>
  )
}

export default function ClientMandate() {
  const { account, reload } = useAccount()
  const [editing, setEditing] = useState(false)
  const m = account?.mandate
  if (!account) return null

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-emphasis">Your agent’s rules</h1>
          <p className="text-sm text-muted-foreground">What your AI agent may buy on its own. Valio Aimo’s server enforces these; the agent cannot change them.</p>
        </div>
        {m && !editing && (
          <Button variant="outline" onClick={() => setEditing(true)}>
            <Pencil /> Edit
          </Button>
        )}
      </div>
      <Card className="gap-0 p-5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {account.mandate_verified ? (
            <Chip tone="ok">
              <BadgeCheck className="size-3.5" /> Signed by you · checked
            </Chip>
          ) : (
            <Chip tone="stop">
              <AlertTriangle className="size-3.5" /> {account.mandate_problem ?? 'Signature not valid'}
            </Chip>
          )}
          {m && <Chip>valid until {shortDate(m.valid_until)}</Chip>}
          {m && <span className="ml-auto font-mono text-[11px] text-muted-foreground">{m.mandate_id}</span>}
        </div>
        {!m ? (
          <p className="text-sm text-muted-foreground">No mandate on file.</p>
        ) : editing ? (
          <Editor
            account={account}
            m={m}
            onDone={() => {
              setEditing(false)
              reload()
            }}
          />
        ) : (
          <Rules m={m} />
        )}
      </Card>
    </div>
  )
}
