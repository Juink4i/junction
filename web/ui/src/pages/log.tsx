import { useEffect, useMemo, useRef, useState } from "react"
import { LinkIcon, ScrollTextIcon, SearchIcon, ShieldAlertIcon, ShieldCheckIcon, ShieldIcon, ShieldXIcon } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { PageHeader } from "@/components/page"
import { ActorPill, LinkDot, Pill, STATUS, type Actor } from "@/components/status"
import { asList, getJSON } from "@/lib/api"
import { usePoll, type LinkState } from "@/lib/events"
import { clock } from "@/lib/format"
import { mount } from "@/lib/mount"
import type { LogEntry, Verdict } from "@/lib/types"
import { cn } from "@/lib/utils"

function actorOf(actor?: string): Exclude<Actor, "mcp"> {
  const a = String(actor ?? "").toLowerCase()
  if (a.includes("policy") || a.includes("server") || a.includes("auditor")) return "code"
  if (a.includes("approver") || a.includes("@") || a.includes("human")) return "person"
  return "ai"
}

function ActionLabel({ action }: { action?: string }) {
  const a = String(action ?? "")
  for (const [k, s] of Object.entries(STATUS)) if (a.includes(k)) return <Pill tone={s.tone} icon={s.icon}>{a}</Pill>
  return <span className="font-mono text-[13px] font-semibold">{a}</span>
}

type Check =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "ok"; count: number }
  | { state: "bad"; at: number | null }
  | { state: "error"; message: string }

function VerifyPanel({ check, onVerify }: { check: Check; onVerify: () => void }) {
  const tone =
    check.state === "ok" ? "bg-success-soft text-success border-transparent" : check.state === "bad" || check.state === "error" ? "bg-destructive-soft text-destructive border-transparent" : "bg-card"
  const Icon = check.state === "ok" ? ShieldCheckIcon : check.state === "bad" || check.state === "error" ? ShieldXIcon : ShieldIcon
  const title =
    check.state === "ok"
      ? "Log intact"
      : check.state === "bad"
        ? `Log broken at entry #${check.at}`
        : check.state === "error"
          ? "Could not verify"
          : "Is this log intact?"
  const text =
    check.state === "ok"
      ? `All ${check.count} entries checked. Every hash matches the entry before it.`
      : check.state === "bad"
        ? `Entry #${check.at} was changed after it was written, so it and every later hash no longer match.`
        : check.state === "error"
          ? check.message
          : "Each entry stores the hash of the entry before it. Edit one row and every later hash stops matching."
  return (
    <section className={cn("sticky top-[61px] z-10 flex flex-wrap items-center gap-4 rounded-xl border p-4 shadow-sm transition-colors", tone)}>
      <Icon className={cn("size-8 shrink-0", check.state === "idle" || check.state === "checking" ? "text-muted-foreground" : "")} />
      <div className="min-w-[220px] flex-1">
        <div className="text-base font-semibold">{title}</div>
        <p className={cn("text-sm text-pretty", check.state === "idle" || check.state === "checking" ? "text-muted-foreground" : "opacity-90")}>{text}</p>
      </div>
      <Button
        size="lg"
        className={cn(
          "min-w-36",
          check.state === "ok" && "bg-success text-white hover:bg-success/90 dark:text-neutral-950",
          (check.state === "bad" || check.state === "error") && "bg-destructive text-white hover:bg-destructive/90",
        )}
        disabled={check.state === "checking"}
        onClick={onVerify}
      >
        {check.state === "checking" ? (
          <>
            <Spinner /> Checking
          </>
        ) : check.state === "idle" ? (
          "Verify log"
        ) : (
          "Verify again"
        )}
      </Button>
    </section>
  )
}

function Row({ e, broken, fresh }: { e: LogEntry; broken: "broken" | "after" | null; fresh: boolean }) {
  return (
    <li
      id={`e${e.seq}`}
      className={cn(
        "grid grid-cols-[48px_1fr] gap-x-3 gap-y-1 rounded-lg border bg-card px-4 py-3",
        fresh && "animate-in fade-in slide-in-from-top-1 duration-300",
        broken === "broken" && "border-destructive bg-destructive-soft ring-2 ring-destructive/30",
        broken === "after" && "border-dashed border-destructive/50 opacity-60",
      )}
    >
      <span className="pt-0.5 font-mono text-[13px] text-muted-foreground tabular-nums">#{e.seq}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <ActorPill actor={actorOf(e.actor)}>{e.actor}</ActorPill>
        <ActionLabel action={e.action} />
        <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">{clock(e.time)}</span>
      </div>
      <p className="col-start-2 text-sm text-pretty">{e.reason}</p>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="col-start-2 flex w-fit max-w-full items-center gap-1.5 truncate font-mono text-[11px] text-muted-foreground/80">
            <LinkIcon className="size-3 shrink-0" />
            prev {String(e.prev_hash ?? "").slice(0, 12)}… → {String(e.hash ?? "").slice(0, 12)}…
          </div>
        </TooltipTrigger>
        <TooltipContent className="max-w-md font-mono text-[11px] break-all">
          prev {e.prev_hash}
          <br />
          hash {e.hash}
        </TooltipContent>
      </Tooltip>
    </li>
  )
}

type Who = "all" | "ai" | "code" | "person"

function LogPage() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [loaded, setLoaded] = useState(false)
  const [link, setLink] = useState<LinkState>("connecting")
  const [error, setError] = useState("")
  const [query, setQuery] = useState("")
  const [who, setWho] = useState<Who>("all")
  const [auto, setAuto] = useState(true)
  const [check, setCheck] = useState<Check>({ state: "idle" })
  const sig = useRef("")
  const seen = useRef(new Set<number>())
  const firstLoad = useRef(true)

  const load = async () => {
    try {
      const next = asList<LogEntry>(await getJSON("/api/log"), "entries", "items", "log")
      const s = JSON.stringify(next)
      if (s !== sig.current) {
        sig.current = s
        setEntries(next)
      }
      setLoaded(true)
      setLink("live")
      setError("")
      return next
    } catch (e) {
      setLink("offline")
      setError((e as Error).message)
      return null
    }
  }

  usePoll(async () => void (await load()), 3000, auto)

  // Remember which rows were already on screen, so only new ones animate in.
  useEffect(() => {
    const t = setTimeout(() => {
      entries.forEach((e) => seen.current.add(e.seq))
      firstLoad.current = false
    }, 400)
    return () => clearTimeout(t)
  }, [entries])

  const verify = async () => {
    setCheck({ state: "checking" })
    try {
      const list = (await load()) ?? entries
      const r = await getJSON<Verdict>("/api/log/verify")
      if (r.ok) setCheck({ state: "ok", count: list.length })
      else {
        setCheck({ state: "bad", at: r.broken_at_seq ?? null })
        setTimeout(() => document.getElementById(`e${r.broken_at_seq}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50)
      }
    } catch (e) {
      setCheck({ state: "error", message: (e as Error).message })
    }
  }

  useEffect(() => {
    if (new URLSearchParams(location.search).get("verify") === "1") setTimeout(verify, 300)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const brokenAt = check.state === "bad" ? check.at : null
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return entries
      .filter((e) => who === "all" || actorOf(e.actor) === who)
      .filter((e) => !q || JSON.stringify(e).toLowerCase().includes(q))
      .slice()
      .reverse()
  }, [entries, query, who])

  return (
    <div className="min-h-dvh">
      <PageHeader
        width="max-w-4xl"
        title="Decision log"
        sub="Every search, quote, decision and approval, in plain language. The buyer and Valio Aimo read the same log."
        right={<LinkDot state={link} />}
      />
      <main className="mx-auto max-w-4xl space-y-4 p-4">
        <VerifyPanel check={check} onVerify={verify} />

        <div className="flex flex-wrap items-center gap-3">
          <InputGroup className="h-9 min-w-[200px] flex-1 bg-card">
            <InputGroupInput
              type="search"
              placeholder="Filter: order id, buyer, decision…"
              aria-label="Filter log"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <InputGroupAddon>
              <SearchIcon />
            </InputGroupAddon>
          </InputGroup>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            spacing={0}
            value={who}
            onValueChange={(v) => v && setWho(v as Who)}
            aria-label="Who acted"
            className="bg-card"
          >
            <ToggleGroupItem value="all">All</ToggleGroupItem>
            <ToggleGroupItem value="ai">Agent</ToggleGroupItem>
            <ToggleGroupItem value="code">Code</ToggleGroupItem>
            <ToggleGroupItem value="person">Person</ToggleGroupItem>
          </ToggleGroup>
          <div className="flex items-center gap-2">
            <Switch id="auto" checked={auto} onCheckedChange={setAuto} />
            <Label htmlFor="auto" className="text-[13px] font-normal text-muted-foreground">
              Auto-refresh
            </Label>
          </div>
          {entries.length > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {shown.length === entries.length ? `${entries.length} entries` : `${shown.length} of ${entries.length}`}
            </span>
          )}
        </div>

        {error && (
          <Alert variant="destructive" className="bg-destructive-soft">
            <ShieldAlertIcon />
            <AlertTitle>Can't reach the trade server</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {shown.length > 0 && (
          <ol className="space-y-2">
            {shown.map((e) => (
              <Row
                key={e.seq}
                e={e}
                fresh={!firstLoad.current && !seen.current.has(e.seq)}
                broken={brokenAt == null ? null : e.seq === brokenAt ? "broken" : e.seq > brokenAt ? "after" : null}
              />
            ))}
          </ol>
        )}

        {loaded && shown.length === 0 && (
          <Empty className="py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ScrollTextIcon />
              </EmptyMedia>
              <EmptyTitle>{entries.length ? "Nothing matches" : "No entries yet"}</EmptyTitle>
              <EmptyDescription>
                {entries.length ? "Try another filter." : "Searches, quotes and decisions appear here as the agent works."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </main>
    </div>
  )
}

mount(<LogPage />)
