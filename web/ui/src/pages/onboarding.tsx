import { useEffect, useRef, useState, type ReactNode } from "react"
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  CircleAlertIcon,
  CircleCheckBigIcon,
  PenLineIcon,
  PlusIcon,
  ShieldCheckIcon,
  StoreIcon,
  Trash2Icon,
  TruckIcon,
  WalletIcon,
  type LucideIcon,
} from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { PageHeader } from "@/components/page"
import { getJSON, postJSON } from "@/lib/api"
import { mount } from "@/lib/mount"
import { numberOrNull, type Answers, type Choice, type Options, type Preview, type SignedUp } from "@/lib/onboarding"
import { cn } from "@/lib/utils"

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

function Section({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span className="inline-flex size-7 items-center justify-center rounded-md bg-brand-soft text-brand">
            <Icon className="size-4" />
          </span>
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-5">{children}</FieldGroup>
      </CardContent>
    </Card>
  )
}

const chip =
  "h-8 rounded-full! border px-3 text-[13px] data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"

function Chip({ c, short }: { c: Choice; short?: boolean }) {
  return (
    <ToggleGroupItem value={c.code} aria-label={c.name} className={chip}>
      <CheckIcon className="hidden size-3.5 group-data-[state=on]/toggle:block" aria-hidden />
      {short ? c.name.slice(0, 3) : c.name}
    </ToggleGroupItem>
  )
}

function Chips({ items, value, onChange, short }: { items: Choice[]; value: string[]; onChange: (v: string[]) => void; short?: boolean }) {
  return (
    <ToggleGroup type="multiple" variant="outline" spacing={2} value={value} onValueChange={onChange} className="flex-wrap">
      {items.map((c) => (
        <Chip key={c.code} c={c} short={short} />
      ))}
    </ToggleGroup>
  )
}

function OneOf({ items, value, onChange }: { items: Choice[]; value: string; onChange: (v: string) => void }) {
  return (
    <ToggleGroup type="single" variant="outline" spacing={2} value={value} onValueChange={(v) => v && onChange(v)} className="flex-wrap">
      {items.map((c) => (
        <Chip key={c.code} c={c} />
      ))}
    </ToggleGroup>
  )
}

function Pick({ items, value, onChange, label, className }: {
  items: Choice[]
  value: string
  onChange: (v: string) => void
  label: string
  className?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className={cn("w-full", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((c) => (
          <SelectItem key={c.code} value={c.code}>
            {c.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Form({ opts, a, update, budgetPeriod, setBudgetPeriod }: {
  opts: Options
  a: Answers
  update: (fn: (d: Answers) => void) => void
  budgetPeriod: string
  setBudgetPeriod: (p: string) => void
}) {
  const names = Object.fromEntries(opts.priorities.map((p) => [p.code, p.name]))
  const perPeriod = opts.periods.map((p) => ({ code: p.code, name: "per " + p.name }))
  const every = opts.periods.map((p) => ({ code: p.code, name: "every " + p.name }))
  const units = [
    { code: "L", name: "L" },
    { code: "KG", name: "kg" },
  ]
  const move = (i: number, by: -1 | 1) =>
    update((d) => {
      const p = d.money.priorities
      ;[p[i], p[i + by]] = [p[i + by], p[i]]
    })

  return (
    <>
      <Section icon={StoreIcon} title="Your kitchen">
        <Field>
          <FieldLabel htmlFor="name">Kitchen name</FieldLabel>
          <Input id="name" value={a.kitchen.name} onChange={(e) => update((d) => void (d.kitchen.name = e.target.value))} />
        </Field>
        <Field>
          <FieldLabel htmlFor="approver">Who approves what the agent may not order alone</FieldLabel>
          <Input
            id="approver"
            type="email"
            value={a.kitchen.approver}
            onChange={(e) => update((d) => void (d.kitchen.approver = e.target.value))}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="enrolment_code">Valio Aimo enrolment code</FieldLabel>
          <Input
            id="enrolment_code"
            className="font-mono tracking-wide"
            value={a.kitchen.enrolment_code}
            onChange={(e) => update((d) => void (d.kitchen.enrolment_code = e.target.value))}
          />
          <FieldDescription>From your webshop account.</FieldDescription>
        </Field>
      </Section>

      <Section icon={ShieldCheckIcon} title="Food safety">
        <Field>
          <FieldLabel>Allergens that must never arrive</FieldLabel>
          <Chips items={opts.allergens} value={a.safety.blocked_allergens} onChange={(v) => update((d) => void (d.safety.blocked_allergens = v))} />
        </Field>
        <Field>
          <FieldLabel>When a product has no allergen information</FieldLabel>
          <OneOf items={opts.unknown_allergens} value={a.safety.unknown_allergens} onChange={(v) => update((d) => void (d.safety.unknown_allergens = v))} />
        </Field>
        <Field>
          <FieldLabel>
            Every product must be <span className="font-normal text-muted-foreground">(optional)</span>
          </FieldLabel>
          <Chips items={opts.tags} value={a.safety.must_be} onChange={(v) => update((d) => void (d.safety.must_be = v))} />
        </Field>
      </Section>

      <Section icon={WalletIcon} title="Money">
        <Field>
          <FieldLabel>What the agent may buy</FieldLabel>
          <FieldDescription className="-mt-1">None ticked means anything.</FieldDescription>
          <Chips items={opts.categories} value={a.money.allowed_categories} onChange={(v) => update((d) => void (d.money.allowed_categories = v))} />
        </Field>
        <Field>
          <FieldLabel htmlFor="max_order">The agent may spend alone, per order</FieldLabel>
          <InputGroup>
            <InputGroupAddon>€</InputGroupAddon>
            <InputGroupInput
              id="max_order"
              type="number"
              inputMode="decimal"
              min={0}
              step={10}
              className="tabular-nums"
              value={a.money.max_order_eur ?? ""}
              onChange={(e) => update((d) => void (d.money.max_order_eur = numberOrNull(e.target.value)))}
            />
          </InputGroup>
        </Field>
        <Field>
          <FieldLabel htmlFor="budget">Budget</FieldLabel>
          <div className="flex gap-2">
            <InputGroup className="flex-1">
              <InputGroupAddon>€</InputGroupAddon>
              <InputGroupInput
                id="budget"
                type="number"
                inputMode="decimal"
                min={0}
                step={10}
                placeholder="none"
                className="tabular-nums"
                value={a.money.budget?.max_eur ?? ""}
                onChange={(e) =>
                  update((d) => {
                    const v = numberOrNull(e.target.value)
                    d.money.budget = v === null ? null : { period: budgetPeriod, max_eur: v }
                  })
                }
              />
            </InputGroup>
            <Pick
              label="Budget period"
              items={perPeriod}
              value={budgetPeriod}
              className="w-36"
              onChange={(p) => {
                setBudgetPeriod(p)
                update((d) => void (d.money.budget && (d.money.budget.period = p)))
              }}
            />
          </div>
          <FieldDescription>Leave empty for none.</FieldDescription>
        </Field>
        <Field>
          <FieldLabel>What matters most, in order</FieldLabel>
          <ol className="divide-y rounded-lg border">
            {a.money.priorities.map((code, i) => (
              <li key={code} className="flex items-center gap-2 py-1 pr-1 pl-3">
                <span className="w-4 text-sm font-semibold text-muted-foreground tabular-nums">{i + 1}</span>
                <span className="flex-1 text-sm">{cap(names[code] ?? code)}</span>
                <Button type="button" variant="ghost" size="icon-sm" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                  <ArrowUpIcon />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Move down"
                  disabled={i === a.money.priorities.length - 1}
                  onClick={() => move(i, 1)}
                >
                  <ArrowDownIcon />
                </Button>
              </li>
            ))}
          </ol>
        </Field>
      </Section>

      <Section icon={TruckIcon} title="Delivery and rhythm">
        <Field>
          <FieldLabel>Days you can receive goods</FieldLabel>
          <FieldDescription className="-mt-1">None ticked means any day.</FieldDescription>
          <Chips items={opts.weekdays} value={a.delivery.days} onChange={(v) => update((d) => void (d.delivery.days = v))} short />
        </Field>
        <Field>
          <FieldLabel>Pack size</FieldLabel>
          <OneOf items={opts.pack_sizes} value={a.delivery.pack_size} onChange={(v) => update((d) => void (d.delivery.pack_size = v))} />
        </Field>
        <Field>
          <FieldLabel>Usual orders</FieldLabel>
          <FieldDescription className="-mt-1">What, how much, how often.</FieldDescription>
          <div className="space-y-2">
            {a.usual_orders.map((o, i) => (
              <div key={i} className="space-y-2 rounded-lg border bg-muted/30 p-2.5">
                <div className="flex gap-2">
                  <Input
                    aria-label="What"
                    placeholder="What, for example milk"
                    value={o.what}
                    onChange={(e) => update((d) => void (d.usual_orders[i].what = e.target.value))}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Remove"
                    className="shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => update((d) => void d.usual_orders.splice(i, 1))}
                  >
                    <Trash2Icon />
                  </Button>
                </div>
                <Pick
                  label="Category"
                  items={opts.categories}
                  value={o.category}
                  onChange={(v) => update((d) => void (d.usual_orders[i].category = v))}
                />
                <div className="grid grid-cols-[1fr_72px_1.3fr] gap-2">
                  <Input
                    aria-label="Amount"
                    type="number"
                    inputMode="decimal"
                    min={0}
                    className="tabular-nums"
                    value={o.amount ?? ""}
                    onChange={(e) => update((d) => void (d.usual_orders[i].amount = numberOrNull(e.target.value)))}
                  />
                  <Pick label="Unit" items={units} value={o.unit} onChange={(v) => update((d) => void (d.usual_orders[i].unit = v))} />
                  <Pick label="How often" items={every} value={o.every} onChange={(v) => update((d) => void (d.usual_orders[i].every = v))} />
                </div>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              className="w-full border-dashed"
              onClick={() =>
                update((d) =>
                  void d.usual_orders.push({ what: "", category: opts.categories[0].code, amount: null, unit: "L", every: "week" }),
                )
              }
            >
              <PlusIcon /> Add a usual order
            </Button>
          </div>
        </Field>
      </Section>
    </>
  )
}

function Done({ out }: { out: SignedUp }) {
  return (
    <Card className="animate-in items-center gap-3 px-6 py-8 text-center fade-in zoom-in-95">
      <span className="inline-flex size-14 items-center justify-center rounded-full bg-success-soft text-success">
        <CircleCheckBigIcon className="size-7" />
      </span>
      <h2 className="text-xl font-semibold tracking-tight">Signed and registered</h2>
      <p className="text-sm text-pretty text-muted-foreground">
        <span className="font-semibold text-foreground">{out.name}</span> is now a buyer at Valio Aimo. Its agent can order straight away,
        inside the rules it signed.
      </p>
      <div className="mt-1 w-full rounded-lg border bg-muted/40 px-3 py-2">
        <div className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Buyer id</div>
        <code className="font-mono text-sm break-all select-all">{out.buyer_id}</code>
      </div>
    </Card>
  )
}

function OnboardingPage() {
  const [opts, setOpts] = useState<Options | null>(null)
  const [answers, setAnswers] = useState<Answers | null>(null)
  const [budgetPeriod, setBudgetPeriod] = useState("week")
  const [problems, setProblems] = useState<string[] | null>(null)
  const [loadError, setLoadError] = useState("")
  const [signError, setSignError] = useState("")
  const [signing, setSigning] = useState(false)
  const [done, setDone] = useState<SignedUp | null>(null)
  const asked = useRef(0)

  useEffect(() => {
    getJSON<Options>("/api/onboarding/options")
      .then((o) => {
        const preset = new URLSearchParams(location.search).get("preset")
        const kind = preset && o.templates[preset] ? preset : o.kitchen_types[0].code
        const t = structuredClone(o.templates[kind])
        setOpts(o)
        setAnswers(t)
        setBudgetPeriod(t.money.budget?.period ?? "week")
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  // Ask the server what is wrong with the answers, a moment after each change.
  useEffect(() => {
    if (!answers) return
    const n = ++asked.current
    const t = setTimeout(async () => {
      let found: string[]
      try {
        found = (await postJSON<Preview>("/api/onboarding/preview", answers)).problems
      } catch (e) {
        found = [(e as Error).message]
      }
      if (n === asked.current) setProblems(found)
    }, 250)
    return () => clearTimeout(t)
  }, [answers])

  const update = (fn: (d: Answers) => void) => {
    setSignError("")
    setAnswers((prev) => {
      if (!prev) return prev
      const next = structuredClone(prev)
      fn(next)
      return next
    })
  }

  const sign = async () => {
    if (!answers) return
    setSigning(true)
    setSignError("")
    try {
      setDone(await postJSON<SignedUp>("/api/onboarding", answers))
      window.scrollTo({ top: 0 })
    } catch (e) {
      setSignError((e as Error).message)
    } finally {
      setSigning(false)
    }
  }

  const shownProblems = signError ? [signError] : (problems ?? [])

  return (
    <div className="min-h-dvh">
      <PageHeader width="max-w-xl" title="Set up your kitchen" sub="Answer once and sign. Your agent can order straight away." />
      <main className={cn("mx-auto max-w-xl space-y-4 p-4", !done && "pb-40")}>
        {loadError && (
          <Alert variant="destructive" className="bg-destructive-soft">
            <CircleAlertIcon />
            <AlertDescription>The form could not load: {loadError}</AlertDescription>
          </Alert>
        )}
        {done ? (
          <Done out={done} />
        ) : opts && answers ? (
          <Form opts={opts} a={answers} update={update} budgetPeriod={budgetPeriod} setBudgetPeriod={setBudgetPeriod} />
        ) : (
          !loadError && [0, 1, 2].map((i) => <Skeleton key={i} className="h-56 w-full rounded-xl" />)
        )}
      </main>

      {!done && answers && (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t bg-background/85 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur-md">
          <div className="mx-auto max-w-xl space-y-2.5">
            {shownProblems.length > 0 && (
              <Alert variant="destructive" className="max-h-28 overflow-y-auto bg-destructive-soft py-2">
                <CircleAlertIcon />
                <AlertDescription className="text-pretty">
                  {shownProblems.map((p, i) => (
                    <div key={i}>{p}</div>
                  ))}
                </AlertDescription>
              </Alert>
            )}
            <Button size="lg" className="h-11 w-full text-[15px]" disabled={signing || problems === null || problems.length > 0} onClick={sign}>
              {signing ? <Spinner /> : <PenLineIcon />}
              {signing ? "Signing" : "Sign and register"}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

mount(<OnboardingPage />)
