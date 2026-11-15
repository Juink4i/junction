import { BadgeCheck, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { CategoryPicker, Chips, PriorityRanker, UsualOrders } from '@/components/answers'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, type ApiFailure } from '@/lib/api'
import type { OnboardingAnswers, OnboardingOptions } from '@/lib/types'
import { num, select } from '@/lib/utils'

// Shapes from web/ /api/onboarding/* (onboarding/options.py and onboarding/build.py).
type Answers = OnboardingAnswers
type Options = OnboardingOptions
interface Preview {
  problems: string[]
  sentences: unknown[]
}
interface Created {
  buyer_id: string
  name: string
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="gap-4 p-5">
      <h2 className="text-base font-semibold text-emphasis">{title}</h2>
      {children}
    </Card>
  )
}

function Field({ label, htmlFor, children }: { label: ReactNode; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  )
}


/** Sign up a new kitchen: answers → signed mandate → registered at Valio Aimo → its dashboard. */
export default function Onboarding() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [opts, setOpts] = useState<Options | null>(null)
  const [a, setA] = useState<Answers | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [checking, setChecking] = useState(false)
  const [signing, setSigning] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    document.documentElement.classList.remove('dark')
    api<Options>('/onboarding/options')
      .then((o) => {
        setOpts(o)
        const preset = params.get('preset')
        setA(clone(o.templates[preset && o.templates[preset] ? preset : o.kitchen_types[0].code]))
      })
      .catch((e: ApiFailure) => setLoadError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The server checks the answers (same rules it signs with) 250 ms after each change.
  useEffect(() => {
    if (!a) return
    setChecking(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      api<Preview>('/onboarding/preview', { method: 'POST', body: JSON.stringify(a) })
        .then((p) => setProblems(p.problems))
        .catch((e: ApiFailure) => setProblems([e.message]))
        .finally(() => setChecking(false))
    }, 250)
    return () => window.clearTimeout(timer.current)
  }, [a])

  const update = (f: (draft: Answers) => void) =>
    setA((prev) => {
      if (!prev) return prev
      const next = clone(prev)
      f(next)
      return next
    })

  const sign = async () => {
    if (!a) return
    setSigning(true)
    try {
      const out = await api<Created>('/onboarding', { method: 'POST', body: JSON.stringify(a) })
      try {
        localStorage.setItem('tt.account', out.buyer_id)
      } catch {
        /* ignore */
      }
      toast.success(`${out.name} is signed up. Its agent can order straight away, inside the rules it signed.`)
      navigate(`/client?account=${encodeURIComponent(out.buyer_id)}`, { replace: true })
    } catch (e) {
      setProblems([(e as ApiFailure).message])
      setSigning(false)
    }
  }

  if (loadError)
    return (
      <Shell>
        <div className="rounded-lg border border-stop/25 bg-stop-soft p-4 text-sm text-stop">{loadError}</div>
      </Shell>
    )
  if (!opts || !a)
    return (
      <Shell>
        <Skeleton className="h-96 w-full rounded-lg" />
      </Shell>
    )

  return (
    <Shell>
      <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
        <Section title="Your kitchen">
          <Field label="Kitchen name" htmlFor="name">
            <Input id="name" value={a.kitchen.name} onChange={(e) => update((d) => void (d.kitchen.name = e.target.value))} />
          </Field>
          <Field label="Who approves what the agent may not order alone" htmlFor="approver">
            <Input id="approver" type="email" value={a.kitchen.approver} onChange={(e) => update((d) => void (d.kitchen.approver = e.target.value))} />
          </Field>
          <Field label="Valio Aimo enrolment code, from your webshop account" htmlFor="code">
            <Input id="code" value={a.kitchen.enrolment_code} onChange={(e) => update((d) => void (d.kitchen.enrolment_code = e.target.value))} />
          </Field>
        </Section>

        <Section title="Food safety">
          <Field label="Allergens that must never arrive">
            <Chips tone="stop" items={opts.allergens} chosen={a.safety.blocked_allergens} onChange={(v) => update((d) => void (d.safety.blocked_allergens = v))} />
          </Field>
          <Field label="When a product has no allergen information">
            <Chips single items={opts.unknown_allergens} chosen={[a.safety.unknown_allergens]} onChange={(v) => update((d) => void (d.safety.unknown_allergens = v[0]))} />
          </Field>
          <Field label={<>Every product must be <span className="font-normal text-muted-foreground/80">(optional)</span></>}>
            <Chips items={opts.tags} chosen={a.safety.must_be} onChange={(v) => update((d) => void (d.safety.must_be = v))} />
            <p className="text-xs text-muted-foreground">The supplier says so, or its allergen data shows it. If neither says, it follows the missing-allergen setting. Other properties, like low-salt, are preferences.</p>
          </Field>
        </Section>

        <Section title="What the agent may buy">
          <Field label={<>Categories <span className="font-normal text-muted-foreground/80">(optional)</span></>}>
            <CategoryPicker items={opts.categories} chosen={a.money.allowed_categories ?? []} onChange={(v) => update((d) => void (d.money.allowed_categories = v))} />
            <p className="text-xs text-muted-foreground">None picked means any category.</p>
          </Field>
        </Section>

        <Section title="Money">
          <Field label="The agent may spend alone, per order, in euros" htmlFor="max_order">
            <Input
              id="max_order"
              type="number"
              min={0}
              step={10}
              inputMode="decimal"
              value={a.money.max_order_eur ?? ''}
              onChange={(e) => update((d) => void (d.money.max_order_eur = num(e.target.value)))}
            />
          </Field>
          <Field label="Budget in euros. Leave empty for none." htmlFor="budget">
            <div className="flex gap-2">
              <Input
                id="budget"
                type="number"
                min={0}
                step={10}
                inputMode="decimal"
                value={a.money.budget?.max_eur ?? ''}
                onChange={(e) =>
                  update((d) => {
                    const v = num(e.target.value)
                    d.money.budget = v === null ? null : { period: d.money.budget?.period ?? 'week', max_eur: v }
                  })
                }
              />
              <select
                className={select}
                aria-label="Budget period"
                value={a.money.budget?.period ?? 'week'}
                onChange={(e) => update((d) => void (d.money.budget && (d.money.budget.period = e.target.value)))}
                disabled={!a.money.budget}
              >
                {opts.periods.map((p) => (
                  <option key={p.code} value={p.code}>
                    per {p.name}
                  </option>
                ))}
              </select>
            </div>
          </Field>
          <Field label="What matters most, in order">
            <PriorityRanker codes={a.money.priorities} choices={opts.priorities} onChange={(v) => update((d) => void (d.money.priorities = v))} />
          </Field>
          <Field label={<>If two products are equally good, prefer ones that are <span className="font-normal text-muted-foreground/80">(optional)</span></>}>
            <Chips items={opts.prefer_tags} chosen={a.prefer ?? []} onChange={(v) => update((d) => void (d.prefer = v))} />
            <p className="text-xs text-muted-foreground">Nothing is ruled out. A product that claims these ranks higher.</p>
          </Field>
        </Section>

        <Section title="Delivery and rhythm">
          <Field label="Days you can receive goods. None ticked means any day.">
            <Chips items={opts.weekdays} chosen={a.delivery.days} onChange={(v) => update((d) => void (d.delivery.days = v))} />
          </Field>
          <Field label="If two products are equally good, prefer">
            <Chips single items={opts.pack_sizes} chosen={[a.delivery.pack_size]} onChange={(v) => update((d) => void (d.delivery.pack_size = v[0]))} />
            <p className="text-xs text-muted-foreground">Every pack size can still be ordered. This only breaks a tie.</p>
          </Field>
          <Field label="Usual orders: what, how much, how often">
            <UsualOrders orders={a.usual_orders} opts={opts} onChange={(v) => update((d) => void (d.usual_orders = v))} />
          </Field>
        </Section>
      </form>

      {/* Sign bar */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t bg-white/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto max-w-xl space-y-2">
          {problems.length > 0 && (
            <ul className="space-y-0.5 rounded-lg border border-stop/25 bg-stop-soft px-3 py-2 text-sm text-stop" role="alert">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <Button className="h-11 w-full" disabled={signing || checking || problems.length > 0} onClick={sign}>
            {signing ? <Loader2 className="animate-spin" /> : <BadgeCheck />} {signing ? 'Signing' : 'Sign and register'}
          </Button>
        </div>
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-white">
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-xl items-center gap-2 px-4">
          <Link to="/" className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground" aria-label="Trusted Trade">
            <BadgeCheck className="size-4.5" />
          </Link>
          <h1 className="text-base font-semibold text-emphasis">Set up your kitchen</h1>
        </div>
      </header>
      <main className="mx-auto max-w-xl px-4 pt-6 pb-48">
        <p className="mb-4 text-sm text-muted-foreground">
          Your answers become the rules your AI agent must follow. You sign them with your own key; Valio Aimo’s server enforces them on every order.
        </p>
        {children}
      </main>
    </div>
  )
}
