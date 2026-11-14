import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import {
  ArrowDownIcon,
  BotIcon,
  ChevronRightIcon,
  ClipboardListIcon,
  FileSignatureIcon,
  ListOrderedIcon,
  LockIcon,
  MessageCircleQuestionIcon,
  MessagesSquareIcon,
  ShieldAlertIcon,
  SparklesIcon,
  UserIcon,
  CircleCheckIcon,
  BanIcon,
  HourglassIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Spinner } from "@/components/ui/spinner"
import { Markdown } from "@/components/markdown"
import { ActorPill, Pill, statusMeta, toneBorder, toneClass, toneText, type Tone } from "@/components/status"
import { buildFeed, type FeedItem } from "@/lib/feed"
import { dayLabel, eur, num, short } from "@/lib/format"
import { resultSummary } from "@/lib/summary"
import type { AgentEvent, OptionCard, ShoppingRequest } from "@/lib/types"
import { cn } from "@/lib/utils"

const appear = "animate-in fade-in slide-in-from-bottom-1 duration-300"

function Who({ icon: Icon, children, className }: { icon: typeof UserIcon; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mb-1 flex items-center gap-1 text-[11px] font-semibold tracking-wide uppercase", className)}>
      <Icon className="size-3" aria-hidden />
      {children}
    </div>
  )
}

function Panel({ icon: Icon, title, children, className }: {
  icon: typeof UserIcon
  title: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("rounded-xl border bg-card p-3.5 shadow-xs", appear, className)}>
      <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        <Icon className="size-3.5" aria-hidden />
        {title}
      </div>
      {children}
    </div>
  )
}

function SceneBanner({ e }: { e: AgentEvent }) {
  const m = String(e.title ?? "").match(/^(\d+)\s*·\s*(.*)$/)
  return (
    <div className={cn("mt-4 flex gap-4 rounded-xl bg-foreground px-5 py-4 text-background first:mt-0", appear)}>
      {m && <div className="text-3xl leading-none font-semibold tabular-nums opacity-60">{m[1]}</div>}
      <div className="min-w-0">
        <div className="text-lg leading-tight font-semibold tracking-tight">{m ? m[2] : e.title}</div>
        {e.subtitle && <p className="mt-1 text-sm text-pretty opacity-75">{e.subtitle}</p>}
      </div>
    </div>
  )
}

function RunStart({ e }: { e: AgentEvent }) {
  const scripted = String(e.model ?? "").startsWith("scripted")
  return (
    <div className={cn("flex flex-col items-center gap-1.5 py-1 text-center", appear)}>
      <div className="flex flex-wrap items-center justify-center gap-1.5 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{e.buyer_name ?? e.buyer}</span>
        <span aria-hidden>·</span>
        <span>
          buyer agent on <span className="font-mono">{e.model}</span>
        </span>
        {scripted && <Pill>scripted, no AI</Pill>}
        {e.gullible && (
          <Pill tone="danger" icon={ShieldAlertIcon}>
            demo: simulated compromised agent
          </Pill>
        )}
      </div>
      {(e.preferences ?? []).length > 0 && (
        <p className="max-w-prose text-xs text-pretty text-muted-foreground">
          <span className="font-medium">Preferences in use, not rules:</span> {e.preferences!.join(" ")}
        </p>
      )}
    </div>
  )
}

function BuyerBubble({ text }: { text: string }) {
  return (
    <div className={cn("flex justify-end", appear)}>
      <div className="max-w-[86%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2.5 text-primary-foreground shadow-xs">
        <Who icon={UserIcon} className="opacity-75">
          Buyer
        </Who>
        <Markdown text={text} />
      </div>
    </div>
  )
}

function AgentBubble({ text, scripted, asks }: { text: string; scripted?: boolean; asks?: boolean }) {
  return (
    <div className={cn("flex", appear)}>
      <div
        className={cn(
          "max-w-[86%] rounded-2xl rounded-bl-md border px-3.5 py-2.5 shadow-xs",
          asks ? "border-info/50 bg-info-soft" : "bg-card",
        )}
      >
        {asks ? (
          <Who icon={MessageCircleQuestionIcon} className="text-info">
            Agent asks the buyer
          </Who>
        ) : (
          <Who icon={scripted ? BotIcon : SparklesIcon} className="text-brand">
            {scripted ? "Buyer agent · scripted, no AI" : "Buyer agent · AI"}
          </Who>
        )}
        <Markdown text={text} />
      </div>
    </div>
  )
}

function RequestCard({ e }: { e: AgentEvent }) {
  const r = (e.request ?? {}) as ShoppingRequest
  const rows: [string, React.ReactNode][] = [
    ["Product", r.product],
    ["Amount", `${num(r.amount)} ${r.unit ?? ""}`],
    ["Need by", r.need_by ? `${dayLabel(r.need_by)} (${r.need_by})` : "—"],
    [
      "Must have",
      (r.must_have ?? []).length ? (
        <span key="tags" className="flex flex-wrap gap-1">
          {r.must_have!.map((t) => (
            <span key={t} className="rounded-md border px-1.5 py-px font-mono text-[11px] font-medium">
              {t}
            </span>
          ))}
        </span>
      ) : (
        "—"
      ),
    ],
  ]
  if ((r.avoid ?? []).length) rows.push(["Avoid", r.avoid!.join(", ")])
  if (r.notes) rows.push(["Notes", r.notes])
  return (
    <Panel icon={ClipboardListIcon} title="Structured request · written by the agent">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  )
}

function ToolRow({ call, result }: { call: AgentEvent; result?: AgentEvent }) {
  const [open, setOpen] = useState(false)
  const s = result ? resultSummary(call.tool, result.result ?? {}) : null
  return (
    <Collapsible open={open} onOpenChange={setOpen} className={cn("ml-3 border-l-2 pl-3", appear)}>
      <CollapsibleTrigger className="group flex w-full min-w-0 items-center gap-2 rounded-md py-0.5 text-left text-[13px] hover:bg-muted/60">
        <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
        <ActorPill actor="mcp" />
        <span className="shrink-0 font-mono text-xs font-semibold">{call.tool}</span>
        <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground/80">{short(call.args, 120)}</span>
        <span className={cn("ml-auto shrink-0 pl-2 text-xs", s?.error ? "text-destructive" : "text-foreground/80")}>
          {s ? <span className="line-clamp-1 max-w-[40ch]">→ {s.text}</span> : <Spinner className="size-3.5" />}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="scrollbar-thin mt-1.5 mb-1 max-h-72 overflow-auto rounded-lg border bg-muted/50 p-2.5 font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap">
          {JSON.stringify(call.args, null, 2)}
        </pre>
        {result && (
          <pre className="scrollbar-thin mb-1 max-h-72 overflow-auto rounded-lg border bg-muted/50 p-2.5 font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap">
            {(() => {
              const json = JSON.stringify(result.result, null, 2) ?? ""
              return json.length > 6000 ? json.slice(0, 6000) + "\n…" : json
            })()}
          </pre>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

const LABEL_TONE: Record<string, Tone> = { best: "success", better: "info", good: "neutral", split: "code" }

function Options({ e }: { e: AgentEvent }) {
  const opts = e.options ?? []
  return (
    <Panel icon={ListOrderedIcon} title={`${e.title ?? "Options"} · ranked by the agent`}>
      <ol className="divide-y">
        {opts.map((o: OptionCard, i) => {
          const meta = [
            o.units != null ? `${num(o.units)} × ${o.sales_unit ?? "unit"}` : "",
            o.covers != null ? `covers ${num(o.covers)} ${o.content_unit ?? ""}` : "",
            o.available_date ? `arrives ${dayLabel(o.available_date)}` : "",
            o.delivery_reliability != null ? `${Math.round(o.delivery_reliability * 100)}% delivered as ordered` : "",
            o.carbon_kg_per_kg != null ? `${num(o.carbon_kg_per_kg)} kg CO₂e/kg` : "",
          ].filter(Boolean)
          return (
            <li key={i} className="grid grid-cols-[auto_1fr_auto] items-start gap-x-3 gap-y-0.5 py-2.5 first:pt-0 last:pb-0">
              <Pill tone={LABEL_TONE[String(o.label).toLowerCase()] ?? "neutral"} className="mt-0.5 uppercase">
                {o.label}
              </Pill>
              <span className="text-sm font-medium">{o.name}</span>
              <span className="text-right text-sm font-semibold tabular-nums">{eur(o.total_eur)}</span>
              {meta.length > 0 && <span className="col-span-2 col-start-2 text-xs text-muted-foreground">{meta.join(" · ")}</span>}
              {o.trade_off && <span className="col-span-2 col-start-2 text-[13px] text-pretty">{o.trade_off}</span>}
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

function Waiting({ ended }: { ended?: "approved" | "rejected" | "pending" }) {
  const text = !ended
    ? "Waiting for a person to approve on the phone…"
    : ended === "pending"
      ? "Nobody decided yet. The order stays on hold."
      : `Decision received: ${ended}.`
  const Icon = ended === "approved" ? CircleCheckIcon : ended === "rejected" ? BanIcon : HourglassIcon
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-sm font-medium",
        ended ? "bg-muted text-muted-foreground" : toneClass.warning,
        appear,
      )}
    >
      {ended ? <Icon className="size-4" /> : <Spinner className="size-4" />}
      {text}
    </div>
  )
}

function Decision({ e }: { e: AgentEvent }) {
  const s = statusMeta(e.status)
  const label = e.status === "rejected" && e.decided_by ? "Rejected by a person" : s.label
  const Icon = s.icon
  return (
    <div className={cn("rounded-xl border border-l-4 bg-card px-3.5 py-3 shadow-xs", toneBorder[s.tone], appear)}>
      <div className="flex flex-wrap items-center gap-2">
        {e.decided_by ? <ActorPill actor="person" /> : <ActorPill actor="code">trade server rules · code</ActorPill>}
        <span className={cn("flex items-center gap-1.5 font-semibold", toneText[s.tone])}>
          <Icon className="size-4" />
          {label}
        </span>
        {e.decided_by && <span className="ml-auto text-xs text-muted-foreground">{e.decided_by}</span>}
      </div>
      {(e.reasons ?? []).length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-pretty">
          {e.reasons!.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {e.question && <p className="mt-2 text-sm text-pretty italic">Server asks: “{e.question}”</p>}
    </div>
  )
}

function Verify({ e }: { e: AgentEvent }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-xl px-4 py-3.5 text-base font-semibold",
        e.ok ? toneClass.success : toneClass.danger,
        appear,
      )}
    >
      <LockIcon className="size-5" />
      {e.ok
        ? `Verify log: intact. ${e.count ? `${e.count} entries, ` : ""}every hash matches.`
        : `Verify log: broken at entry #${e.broken_at_seq}.`}
    </div>
  )
}

function Onboarded({ e }: { e: AgentEvent }) {
  return (
    <Panel icon={FileSignatureIcon} title={`${e.buyer_name} signed its mandate · rules for the server, preferences for its agent`}>
      <ul className="divide-y">
        {(e.sentences ?? []).map((s, i) => {
          const rule = s.kind === "rule"
          return (
            <li key={i} className="flex items-start gap-2.5 py-1.5 text-sm first:pt-0 last:pb-0">
              <Pill tone={rule ? "code" : "brand"} className="mt-0.5 w-[78px] justify-center">
                {rule ? "Rule" : "Preference"}
              </Pill>
              <span className="text-pretty">{s.text}</span>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

function Item({ item }: { item: FeedItem }) {
  switch (item.type) {
    case "scene":
      return <SceneBanner e={item.e} />
    case "run_start":
      return <RunStart e={item.e} />
    case "buyer":
      return <BuyerBubble text={item.text} />
    case "agent":
      return <AgentBubble text={item.text} scripted={item.scripted} />
    case "ask":
      return <AgentBubble text={item.text} asks />
    case "request":
      return <RequestCard e={item.e} />
    case "tool":
      return <ToolRow call={item.call} result={item.result} />
    case "options":
      return <Options e={item.e} />
    case "waiting":
      return <Waiting ended={item.ended} />
    case "decision":
      return <Decision e={item.e} />
    case "verify":
      return <Verify e={item.e} />
    case "onboarded":
      return <Onboarded e={item.e} />
    case "note":
      return <p className={cn("px-4 text-center text-xs text-pretty text-muted-foreground", appear)}>{item.text}</p>
  }
}

/** The live conversation. Owns its scroll box and keeps to the bottom unless the reader scrolls up. */
export function ChatFeed({ events, className, inner }: { events: AgentEvent[]; className?: string; inner?: string }) {
  const items = useMemo(() => buildFeed(events), [events])
  const box = useRef<HTMLDivElement>(null)
  const [follow, setFollow] = useState(true)
  const [behind, setBehind] = useState(false)

  // Following jumps straight to the end. A smooth scroll would fire scroll events part-way,
  // read as "the reader scrolled up", and stop following during a burst of events.
  const toBottom = (smooth = false) =>
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: smooth ? "smooth" : "auto" })

  useLayoutEffect(() => {
    if (follow) toBottom()
    else if (items.length) setBehind(true)
  }, [items, follow])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const onScroll = () => {
      const atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 80
      setFollow(atEnd)
      if (atEnd) setBehind(false)
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

  return (
    <div className={cn("relative min-h-0", className)}>
      <div ref={box} className="scrollbar-thin h-full overflow-y-auto">
        {items.length === 0 ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <MessagesSquareIcon />
              </EmptyMedia>
              <EmptyTitle>Waiting for the agent</EmptyTitle>
              <EmptyDescription>
                Run <code className="rounded bg-muted px-1 font-mono text-xs">uv run python demo/run.py</code> or{" "}
                <code className="rounded bg-muted px-1 font-mono text-xs">uv run python -m agent "…"</code>
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className={cn("flex flex-col gap-2.5 p-4 pb-10", inner)}>
            {items.map((item) => (
              <Item key={item.key} item={item} />
            ))}
          </div>
        )}
      </div>
      {behind && (
        <Button
          size="sm"
          variant="secondary"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md"
          onClick={() => {
            setFollow(true)
            setBehind(false)
            toBottom(true)
          }}
        >
          <ArrowDownIcon /> Latest
        </Button>
      )}
    </div>
  )
}
