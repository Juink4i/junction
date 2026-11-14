import { useEffect, useMemo, useRef, useState } from "react"
import { QRCodeSVG } from "qrcode.react"
import { ExternalLinkIcon, SmartphoneIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ChatFeed } from "@/components/chat-feed"
import { BrandMark } from "@/components/page"
import { ActorPill, LinkDot } from "@/components/status"
import { getJSON } from "@/lib/api"
import { useEventStream } from "@/lib/events"
import { currentScene } from "@/lib/feed"
import { mount } from "@/lib/mount"
import type { AgentEvent } from "@/lib/types"

const APPROVALS = { path: "/approvals", label: "Procurement manager's phone" }

const LINKS = [
  { href: "/chat", label: "Chat" },
  { href: "/approvals", label: "Approvals" },
  { href: "/log", label: "Log" },
  { href: "/onboarding", label: "Sign-up" },
]

function Stage() {
  // The phone frame follows the demo: the onboarding page while a kitchen signs up,
  // the approvals page otherwise.
  const [phone, setPhone] = useState(APPROVALS)
  const back = useRef<ReturnType<typeof setTimeout>>(undefined)
  const onEvent = (e: AgentEvent) => {
    if (e.kind === "scene") {
      clearTimeout(back.current)
      setPhone(
        e.onboard
          ? { path: "/onboarding?preset=" + encodeURIComponent(e.onboard), label: "Kitchen manager's phone" }
          : APPROVALS,
      )
    } else if (e.kind === "onboarded") {
      clearTimeout(back.current)
      back.current = setTimeout(() => setPhone(APPROVALS), 3000)
    } else if (e.kind === "clear") {
      clearTimeout(back.current)
      setPhone(APPROVALS)
    }
  }
  const { events, link } = useEventStream(onEvent)
  const scene = useMemo(() => currentScene(events), [events])

  const [phoneUrl, setPhoneUrl] = useState(location.origin + "/approvals")
  useEffect(() => {
    getJSON<{ phone_url?: string }>("/api/info")
      .then((info) => info.phone_url && setPhoneUrl(info.phone_url))
      .catch(() => {})
  }, [])

  return (
    <div className="flex min-h-dvh flex-col bg-canvas lg:h-dvh">
      <header className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b bg-background px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <BrandMark />
          <div className="min-w-0">
            <h1 className="text-[17px] leading-tight font-semibold tracking-tight">Trusted Trade Agents</h1>
            <p className="text-[13px] text-muted-foreground">
              An open front door for Valio Aimo. <span className="font-medium text-foreground">The AI suggests. Plain code decides.</span>
            </p>
          </div>
        </div>
        {scene && (
          <div key={scene.id} className="flex min-w-0 animate-in items-center gap-2 rounded-full border bg-card py-1 pr-3.5 pl-1.5 text-sm shadow-xs fade-in slide-in-from-top-1">
            <span className="rounded-full bg-foreground px-2 py-0.5 text-[11px] font-semibold tracking-wide text-background uppercase">Now</span>
            <span className="truncate font-medium">{scene.title}</span>
          </div>
        )}
        <div className="ml-auto flex items-center gap-3">
          <LinkDot state={link} />
          <nav className="flex items-center gap-0.5">
            {LINKS.map((l) => (
              <Button key={l.href} variant="ghost" size="sm" asChild>
                <a href={l.href} target="_blank" rel="noreferrer">
                  {l.label}
                </a>
              </Button>
            ))}
          </nav>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_400px]">
        <section className="flex h-[70vh] min-h-0 flex-col overflow-hidden rounded-xl border bg-background shadow-sm lg:h-auto">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b bg-card px-4 py-2.5">
            <h2 className="text-sm font-semibold">Buyer agent ↔ trade server</h2>
            <span className="rounded-md border px-1.5 py-px font-mono text-[11px] text-muted-foreground">MCP</span>
            <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
              <ActorPill actor="ai" />
              <ActorPill actor="mcp">tool call</ActorPill>
              <ActorPill actor="code" />
              <ActorPill actor="person" />
            </div>
          </div>
          <ChatFeed events={events} className="flex-1" inner="mx-auto w-full max-w-3xl" />
        </section>

        <section className="flex min-h-0 flex-col items-center gap-3">
          <h2 id="phonelabel" className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <SmartphoneIcon className="size-3.5" />
            {phone.label}
          </h2>
          <div className="relative h-[min(780px,calc(100dvh-280px))] min-h-[480px] [@media(max-height:820px)]:h-[calc(100dvh-150px)] w-full max-w-[380px] shrink-0 rounded-[44px] bg-neutral-900 p-3 shadow-[0_20px_50px_-12px_rgb(0_0_0/0.35)] ring-1 ring-black/40">
            <div className="absolute top-[18px] left-1/2 z-10 h-[22px] w-[92px] -translate-x-1/2 rounded-full bg-black" aria-hidden />
            <div className="h-full w-full overflow-hidden rounded-[34px] bg-background pt-7">
              <iframe id="phoneframe" key={phone.path} src={phone.path} title="Phone" className="block h-full w-full border-0" />
            </div>
          </div>
          <div className="flex w-full max-w-[380px] items-center gap-3 rounded-xl border bg-card p-2.5 text-xs text-muted-foreground shadow-xs [@media(max-height:820px)]:hidden">
            <div className="shrink-0 rounded-md bg-white p-1.5 leading-none">
              <QRCodeSVG value={phoneUrl} size={72} />
            </div>
            <div className="min-w-0">
              <p className="font-medium text-foreground">Approve on your own phone</p>
              <p>Same Wi-Fi. Scan, or open:</p>
              <a href={phoneUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono break-all text-foreground hover:underline">
                {phoneUrl}
                <ExternalLinkIcon className="size-3 shrink-0" />
              </a>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

mount(<Stage />)
