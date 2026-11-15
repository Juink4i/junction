import { AlertTriangle, BadgeCheck, Ban, CalendarClock, Euro, Loader2, Package, Pencil, Repeat, ShieldAlert, Sparkles, Tags, UserCheck, Wallet } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Chips, PriorityRanker, UsualOrders } from '@/components/answers'
import { AllergenChips, Chip, TagChips } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccount } from '@/lib/account'
import { accountPath, api, usePoll, type ApiFailure } from '@/lib/api'
import { allergenName, categoryName, eur, shortDate, tagName } from '@/lib/format'
import { changesOf, draftOf, type Draft } from '@/lib/mandate-draft'
import type { Account, Choice, Mandate, OnboardingOptions, Profile } from '@/lib/types'

const nameIn = (choices: Choice[], code: string) => choices.find((c) => c.code === code)?.name ?? code

/** The options list, plus any code the mandate already holds that the list lacks, so it can still be removed. */
const withHeld = (choices: Choice[], held: string[], name: (code: string) => string): Choice[] => [
  ...choices,
  ...held.filter((code) => !choices.some((c) => c.code === code)).map((code) => ({ code, name: name(code) })),
]

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

function Rules({ m, profile, opts }: { m: Mandate; profile: Profile | null; opts: OnboardingOptions }) {
  const day = (code: string) => nameIn(opts.weekdays, code)
  return (
    <ul className="divide-y">
      <Rule icon={<Euro className="size-4" />} title="Orders on its own up to">
        {eur(m.auto_approve.max_order_eur)} per order
        {m.auto_approve.max_line_eur != null && <> and {eur(m.auto_approve.max_line_eur)} per line</>}. Above that, you approve.
      </Rule>
      <Rule icon={<Wallet className="size-4" />} title="Budget">
        {m.budget ? `${eur(m.budget.max_eur)} per ${m.budget.period}. Going over comes to you.` : 'No budget limit.'}
      </Rule>
      {!!m.auto_approve.allowed_categories?.length && (
        <Rule icon={<Tags className="size-4" />} title="Allowed categories">
          {m.auto_approve.allowed_categories.map(categoryName).join(', ')}
        </Rule>
      )}
      {m.substitution.must_keep.length > 0 && (
        <Rule icon={<BadgeCheck className="size-4" />} title="Every product must be">
          <TagChips tags={m.substitution.must_keep} />
          <span className="block text-xs">The supplier says so, or its allergen data shows it. If neither says, it is treated like missing allergen info.</span>
        </Rule>
      )}
      <Rule icon={<Repeat className="size-4" />} title="Substitutes">
        {m.substitution.allowed ? `Allowed, at most ${m.substitution.max_price_increase_pct}% more per litre.` : 'Not allowed.'}
      </Rule>
      <Rule icon={<Ban className="size-4" />} title="Never buy (allergens)">
        {m.hard_rules.blocked_allergens.length ? <AllergenChips codes={m.hard_rules.blocked_allergens} tone="stop" /> : 'Nothing blocked.'}
      </Rule>
      <Rule icon={<ShieldAlert className="size-4" />} title="When allergen info is missing">
        {m.hard_rules.unknown_allergens === 'reject' ? 'Don’t buy it.' : m.hard_rules.unknown_allergens === 'human' ? 'Ask you first. Unknown is never treated as safe.' : 'Buy it anyway.'}
      </Rule>
      <Rule icon={<CalendarClock className="size-4" />} title="Delivery">
        {m.delivery?.days?.length ? `Only on ${m.delivery.days.map(day).join(', ')}. ` : 'Any day. '}
        Must arrive by the date you need it. Another day, or a missed order cut-off, comes to you.
      </Rule>
      {m.usual_orders && m.usual_orders.length > 0 && (
        <Rule icon={<Repeat className="size-4" />} title="Usual orders">
          <ul className="space-y-0.5">
            {m.usual_orders.map((o, i) => (
              <li key={i}>
                {o.amount} {o.content_unit} of {profile?.usual_orders[i]?.what || categoryName(o.category)} every {o.every}
                {o.on != null && (o.every === 'month' ? ` on day ${o.on}` : ` on ${day(String(o.on))}`)}
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

/** Preferences steer which fitting product the agent picks. The server never sees them. */
function Preferences({ profile, opts }: { profile: Profile; opts: OnboardingOptions }) {
  return (
    <ul className="divide-y">
      <Rule icon={<Sparkles className="size-4" />} title="When several products fit, prefer">
        {profile.priorities.map((p) => nameIn(opts.priorities, p)).join(', then ')}.
      </Rule>
      {(profile.prefer?.length ?? 0) > 0 && (
        <Rule icon={<BadgeCheck className="size-4" />} title="If two products are equally good, prefer ones that are">
          <TagChips tags={profile.prefer ?? []} />
        </Rule>
      )}
      <Rule icon={<Package className="size-4" />} title="If two products are equally good">
        Prefer {nameIn(opts.pack_sizes, profile.pack_size)}. Every pack size can still be ordered.
      </Rule>
    </ul>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <span className="block text-sm font-medium text-emphasis">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </div>
  )
}

function Editor({ account, m, profile, opts, onDone }: { account: Account; m: Mandate; profile: Profile | null; opts: OnboardingOptions; onDone: () => void }) {
  const [d, setD] = useState<Draft>(() => draftOf(m, profile))
  const [confirm, setConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const { body, prefs, summary } = changesOf(m, profile, d, opts)
  const signs = Object.keys(body).length > 0

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      if (signs) await api(accountPath(account.buyer_id, '/mandate'), { method: 'PUT', body: JSON.stringify(body) })
      if (Object.keys(prefs).length) await api(accountPath(account.buyer_id, '/profile'), { method: 'PUT', body: JSON.stringify(prefs) })
      toast.success(signs ? 'Signed and saved. Your agent uses the new rules from its next order.' : 'Saved. Your agent uses the new preferences from its next order.')
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
          <Input type="number" min={1} step="any" inputMode="decimal" value={d.maxOrder} onChange={(e) => set('maxOrder', e.target.value)} required aria-label="Most per order" />
        </Field>
        <Field label="Most per line (€)" hint={m.auto_approve.max_line_eur == null ? 'Optional.' : undefined}>
          <Input type="number" min={1} step="any" inputMode="decimal" value={d.maxLine} onChange={(e) => set('maxLine', e.target.value)} required={m.auto_approve.max_line_eur != null} aria-label="Most per line" />
        </Field>
      </div>

      <Field label="Budget (€)" hint="Leave empty for no budget. It cannot be less than the most per order.">
        <div className="flex max-w-sm gap-2">
          <Input type="number" min={1} step="any" inputMode="decimal" value={d.budget} onChange={(e) => set('budget', e.target.value)} aria-label="Budget" />
          <select className="h-9 rounded-md border bg-white px-2 text-sm" value={d.budgetPeriod} onChange={(e) => set('budgetPeriod', e.target.value)} disabled={d.budget === ''} aria-label="Budget period">
            {opts.periods.map((p) => (
              <option key={p.code} value={p.code}>
                per {p.name}
              </option>
            ))}
          </select>
        </div>
      </Field>

      <Field label="Days you can receive goods" hint="None picked means any day.">
        <Chips items={opts.weekdays} chosen={d.days} onChange={(v) => set('days', v)} />
      </Field>

      <div className="space-y-3 rounded-lg border p-4">
        <label className="flex items-center gap-2 text-sm font-medium text-emphasis">
          <input type="checkbox" className="accent-[var(--primary)]" checked={d.subsAllowed} onChange={(e) => set('subsAllowed', e.target.checked)} />
          Allow substitutes when something runs out
        </label>
        {d.subsAllowed && (
          <Field label="May cost up to (% more per litre)">
            <Input className="max-w-32" type="number" min={0} max={100} value={d.subsPct} onChange={(e) => set('subsPct', e.target.value)} aria-label="Substitute price increase" />
          </Field>
        )}
      </div>

      <Field label="Every product must be" hint="The supplier says so, or its allergen data shows it. If neither says, it follows the missing-allergen setting below. Other properties, like low-salt, are preferences.">
        <Chips items={withHeld(opts.tags, d.mustKeep, tagName)} chosen={d.mustKeep} onChange={(v) => set('mustKeep', v)} />
      </Field>

      <Field label="Never buy anything containing">
        <Chips tone="stop" items={withHeld(opts.allergens, d.blocked, allergenName)} chosen={d.blocked} onChange={(v) => set('blocked', v)} />
      </Field>

      <Field label="When allergen info is missing" hint="Unknown is never treated as safe.">
        <Chips single items={opts.unknown_allergens} chosen={[d.unknown]} onChange={(v) => set('unknown', v[0])} />
      </Field>

      <Field label="Usual orders" hint="An order more than 5 times the usual is checked with you first.">
        <UsualOrders orders={d.usual} opts={opts} named={profile != null} onChange={(v) => set('usual', v)} />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Who approves" hint="Email addresses, separated by commas.">
          <Input value={d.approvers} onChange={(e) => set('approvers', e.target.value)} required aria-label="Who approves" />
        </Field>
        <Field label="Valid until">
          <Input type="date" value={d.validUntil} onChange={(e) => set('validUntil', e.target.value)} required aria-label="Valid until" />
        </Field>
      </div>

      {d.priorities && d.packSize && (
        <div className="space-y-4 rounded-lg border p-4">
          <div>
            <div className="text-sm font-semibold text-emphasis">Preferences</div>
            <div className="text-xs text-muted-foreground">These only steer which fitting product your agent picks. They are not signed.</div>
          </div>
          <Field label="What matters most, in order">
            <PriorityRanker codes={d.priorities} choices={opts.priorities} onChange={(v) => set('priorities', v)} />
          </Field>
          <Field label="If two products are equally good, prefer ones that are" hint="Nothing is ruled out. A product that claims these ranks higher.">
            <Chips items={withHeld(opts.prefer_tags, d.prefer ?? [], tagName)} chosen={d.prefer ?? []} onChange={(v) => set('prefer', v)} />
          </Field>
          <Field label="If two products are equally good, prefer" hint="Every pack size can still be ordered. This only breaks a tie.">
            <Chips single items={opts.pack_sizes} chosen={[d.packSize]} onChange={(v) => set('packSize', v[0])} />
          </Field>
        </div>
      )}

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
          {signs ? 'Review and sign' : 'Review and save'}
        </Button>
      </div>

      <Sheet open={confirm} onOpenChange={setConfirm}>
        <SheetContent side="bottom" className="mx-auto max-w-lg rounded-t-xl">
          <SheetHeader>
            <SheetTitle>{signs ? 'Sign the new rules?' : 'Save your preferences?'}</SheetTitle>
            <SheetDescription>
              {signs
                ? 'Your mandate is signed again with your key. Valio Aimo’s server enforces it from your agent’s next order, and the change is written to the audit log.'
                : 'Your agent reads them from its next order. Valio Aimo’s server does not see them.'}
            </SheetDescription>
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
              {saving ? <Loader2 className="animate-spin" /> : <BadgeCheck />} {signs ? 'Sign and save' : 'Save'}
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
  const { data: opts } = usePoll<OnboardingOptions>('/onboarding/options')
  // A 404 (a demo buyer, who never onboarded) leaves the profile null.
  const { data: profile, loading, reload: reloadProfile } = usePoll<Profile>(account ? accountPath(account.buyer_id, '/profile') : null)
  const m = account?.mandate
  if (!account) return null
  const ready = opts != null && !loading

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-emphasis">Your agent’s rules</h1>
          <p className="text-sm text-muted-foreground">What your AI agent may buy on its own. Valio Aimo’s server enforces these; the agent cannot change them.</p>
        </div>
        {m && ready && !editing && (
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
        ) : !ready ? (
          <Skeleton className="h-80 w-full rounded-lg" />
        ) : editing ? (
          <Editor
            account={account}
            m={m}
            profile={profile}
            opts={opts}
            onDone={() => {
              setEditing(false)
              reload()
              reloadProfile()
            }}
          />
        ) : (
          <Rules m={m} profile={profile} opts={opts} />
        )}
      </Card>
      {profile && opts && !editing && (
        <Card className="mt-4 gap-0 p-5">
          <h2 className="text-base font-semibold text-emphasis">Your preferences</h2>
          <p className="mb-1 text-sm text-muted-foreground">Only your agent reads these, to choose between products that already fit the rules.</p>
          <Preferences profile={profile} opts={opts} />
        </Card>
      )}
    </div>
  )
}
