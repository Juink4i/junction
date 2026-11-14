import { useEffect, useRef, useState } from "react"
import { BanIcon, CheckIcon, CircleCheckIcon, CpuIcon, ShieldAlertIcon, SparklesIcon, XIcon } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { PageHeader } from "@/components/page"
import { LinkDot } from "@/components/status"
import { asList, getJSON, postJSON } from "@/lib/api"
import { usePoll, type LinkState } from "@/lib/events"
import { ago, dayLabel, eur, num } from "@/lib/format"
import { mount } from "@/lib/mount"
import type { Approval, QuoteLine } from "@/lib/types"
import { cn } from "@/lib/utils"

type Act = "approve" | "reject"

interface Entry {
  id: string
  a: Approval
  busy?: Act
  done?: { act: Act; by?: string }
  leaving?: boolean
  fresh?: boolean
}

const idOf = (a: Approval) => String(a.approval_id ?? a.id)
const isPending = (a: Approval) => !a.status || a.status === "pending" || a.status === "pending_approval"

function Line({ l }: { l: QuoteLine }) {
  const parts = [
    l.units != null ? `${num(l.units)} × ${l.sales_unit ?? "unit"}` : "",
    l.covers != null ? `${num(l.covers)} ${l.content_unit ?? ""}` : "",
    l.available_date ? `arrives ${dayLabel(l.available_date)}` : "",
  ].filter(Boolean)
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-3 py-2">
      <span className="text-sm leading-snug">{l.name ?? l.product_id}</span>
      <span className="row-span-2 text-sm font-semibold tabular-nums">{eur(l.line_total_eur)}</span>
      {parts.length > 0 && <span className="text-xs text-muted-foreground">{parts.join(" · ")}</span>}
    </li>
  )
}

function ApprovalCard({ entry, onDecide }: { entry: Entry; onDecide: (act: Act) => void }) {
  const { a, busy, done } = entry
  const lines = a.lines ?? a.quote?.lines ?? []
  const total = a.total_eur ?? a.quote?.total_eur
  const needBy = a.need_by ?? a.quote?.need_by
  const created = a.created_at ?? a.time
  const reasons = a.reasons ?? []
  const rationale = a.agent_rationale ?? a.rationale
  const buyer = a.buyer ?? a.buyer_name ?? a.mandate?.buyer ?? "Buyer"

  return (
    <Card
      className={cn(
        "gap-0 p-0 transition-all duration-500",
        entry.fresh && "animate-in fade-in slide-in-from-top-2 ring-2 ring-warning/60",
        entry.leaving && "translate-x-8 opacity-0",
      )}
    >
      <div className="px-4 pt-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold">{buyer}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{created ? ago(created) : ""}</span>
        </div>
        <div className="mt-1.5 text-[32px] leading-none font-semibold tracking-tight tabular-nums">{eur(total)}</div>
        <div className="mt-1.5 text-[13px] text-muted-foreground">
          excl. VAT
          {needBy && (
            <>
              {" · needed by "}
              <span className="font-medium text-foreground">{dayLabel(needBy)}</span>
            </>
          )}
        </div>
        {lines.length > 0 && (
          <ul className="mt-3 divide-y border-y">
            {lines.map((l, i) => (
              <Line key={i} l={l} />
            ))}
          </ul>
        )}
      </div>

      <div className="mx-4 mt-3 rounded-lg bg-warning-soft px-3 py-2.5 text-warning">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide uppercase">
          <ShieldAlertIcon className="size-3.5" />
          Why it needs you
        </div>
        <ul className="mt-1.5 list-disc space-y-0.5 pl-4.5 text-sm text-pretty text-foreground">
          {(reasons.length ? reasons : ["The buyer's rules require a person."]).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
        <div className="mt-2 flex items-center gap-1 text-[11px] font-medium">
          <CpuIcon className="size-3" />
          Checked by the trade server's rules, not by the AI.
        </div>
      </div>

      {rationale && (
        <div className="mx-4 mt-3 text-[13px] text-muted-foreground">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-brand uppercase">
            <SparklesIcon className="size-3" />
            The agent's reason
          </div>
          <q className="mt-1 block text-pretty italic">{rationale}</q>
        </div>
      )}

      <div className="p-4">
        {done ? (
          <div
            className={cn(
              "flex h-12 items-center justify-center gap-2 rounded-lg text-[15px] font-semibold",
              done.act === "approve" ? "bg-success-soft text-success" : "bg-destructive-soft text-destructive",
            )}
          >
            {done.act === "approve" ? <CircleCheckIcon className="size-5" /> : <BanIcon className="size-5" />}
            {done.act === "approve" ? "Approved" : "Rejected"}
            {done.by && <span className="font-normal opacity-80">by {done.by}</span>}
          </div>
        ) : (
          <div className="grid grid-cols-[1fr_1.4fr] gap-2.5">
            <Button
              variant="outline"
              className="h-12 text-[15px] text-destructive hover:bg-destructive-soft hover:text-destructive"
              disabled={!!busy}
              onClick={() => onDecide("reject")}
            >
              {busy === "reject" ? <Spinner /> : <XIcon />}
              Reject
            </Button>
            <Button
              className="h-12 bg-success text-[15px] text-white hover:bg-success/90 dark:text-neutral-950"
              disabled={!!busy}
              onClick={() => onDecide("approve")}
            >
              {busy === "approve" ? <Spinner /> : <CheckIcon />}
              Approve
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}

function ApprovalsPage() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [loaded, setLoaded] = useState(false)
  const [link, setLink] = useState<LinkState>("connecting")
  const [error, setError] = useState("")
  const gone = useRef(new Set<string>()) // decided on this page: never show again
  const first = useRef(true)
  const entriesRef = useRef(entries)
  entriesRef.current = entries

  usePoll(async () => {
    try {
      const items = asList<Approval>(await getJSON("/api/approvals"), "approvals", "items").filter(isPending)
      const ids = new Set(items.map(idOf))
      const isFirst = first.current
      first.current = false
      if (!isFirst && items.some((a) => !gone.current.has(idOf(a)) && !entriesRef.current.some((e) => e.id === idOf(a))))
        navigator.vibrate?.(180)
      setEntries((prev) => {
        const kept = prev.filter((e) => e.done || ids.has(e.id)).map((e) => ({ ...e, fresh: false }))
        const known = new Set(kept.map((e) => e.id))
        const added = items
          .filter((a) => !known.has(idOf(a)) && !gone.current.has(idOf(a)))
          .map((a) => ({ id: idOf(a), a, fresh: !isFirst }))
        return [...added.reverse(), ...kept]
      })
      setLoaded(true)
      setLink("live")
      setError("")
    } catch (e) {
      setLink("offline")
      setError((e as Error).message)
    }
  }, 2000)

  const patch = (id: string, change: Partial<Entry>) =>
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, ...change } : e)))

  const decide = async (id: string, act: Act) => {
    patch(id, { busy: act })
    try {
      const res = await postJSON<{ decided_by?: string }>(`/api/approvals/${encodeURIComponent(id)}/${act}`)
      gone.current.add(id)
      patch(id, { busy: undefined, done: { act, by: res?.decided_by ?? undefined } })
      setTimeout(() => {
        patch(id, { leaving: true })
        setTimeout(() => setEntries((prev) => prev.filter((e) => e.id !== id)), 500)
      }, 2500)
    } catch (e) {
      patch(id, { busy: undefined })
      setError(`Could not ${act}: ${(e as Error).message}`)
    }
  }

  const waiting = entries.filter((e) => !e.done).length
  useEffect(() => {
    document.title = waiting ? `(${waiting}) Approvals` : "Approvals"
  }, [waiting])

  return (
    <div className="mx-auto min-h-dvh max-w-[480px]">
      <PageHeader
        width="max-w-[480px]"
        title={
          <>
            Approvals
            {waiting > 0 && (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-warning px-1.5 text-xs font-bold text-white tabular-nums dark:text-neutral-950">
                {waiting}
              </span>
            )}
          </>
        }
        sub="Orders your buying agent was not allowed to place alone"
        right={<LinkDot state={link} />}
      />
      <main className="space-y-3 p-4">
        {error && (
          <Alert variant="destructive" className="bg-destructive-soft">
            <ShieldAlertIcon />
            <AlertTitle>Can't reach the trade server</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {!loaded && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {entries.map((e) => (
          <ApprovalCard key={e.id} entry={e} onDecide={(act) => decide(e.id, act)} />
        ))}
        {loaded && entries.length === 0 && (
          <Empty className="py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon" className="size-12 rounded-full bg-success-soft text-success">
                <CircleCheckIcon className="size-6" />
              </EmptyMedia>
              <EmptyTitle>Nothing waiting for you</EmptyTitle>
              <EmptyDescription>New requests appear here automatically.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </main>
    </div>
  )
}

mount(<ApprovalsPage />)
