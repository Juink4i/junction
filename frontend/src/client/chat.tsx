import { ArrowDown, Bot, Building2, Hourglass, Loader2, Send, UserRound } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Alternatives } from '@/components/feed'
import { StatusBadge } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAccount } from '@/lib/account'
import { accountPath, api, ApiFailure, useEvents } from '@/lib/api'
import { dateTime, eur, shortDate, timeOf, unitsBothWays } from '@/lib/format'
import type { AgentEvent } from '@/lib/types'
import { cn } from '@/lib/utils'

type Msg =
  | { id: number; side: 'divider'; text: string; sub?: string }
  | { id: number; side: 'left' | 'right'; who: string; icon: 'agent' | 'valio' | 'buyer'; time?: string; body: ReactNode }

/** Agent events as a plain conversation: the buyer on the right, the agent and server on the left. */
export function toChat(events: AgentEvent[]): Msg[] {
  const out: Msg[] = []
  for (const e of events) {
    switch (e.kind) {
      case 'scene':
        out.push({ id: e.id, side: 'divider', text: e.title ?? 'New conversation', sub: e.subtitle })
        break
      case 'run_start':
        if (out.at(-1)?.side !== 'divider') out.push({ id: e.id, side: 'divider', text: dateTime(e.ts) })
        break
      case 'user':
      case 'answer':
        out.push({ id: e.id, side: 'right', who: 'You', icon: 'buyer', time: e.ts, body: e.text })
        break
      case 'agent':
        out.push({ id: e.id, side: 'left', who: 'Your agent', icon: 'agent', time: e.ts, body: e.text })
        break
      case 'ask':
        out.push({ id: e.id, side: 'left', who: 'Your agent asks', icon: 'agent', time: e.ts, body: <span className="font-medium">{e.question}</span> })
        break
      case 'options':
        out.push({
          id: e.id,
          side: 'left',
          who: 'Your agent',
          icon: 'agent',
          time: e.ts,
          body: (
            <div className="space-y-2">
              <div className="font-medium">{e.title ?? 'Options'}</div>
              <ol className="space-y-1.5">
                {(e.options ?? []).map((o, i) => (
                  <li key={i} className="rounded-md bg-white/70 p-2 text-[13px]">
                    <span className="mr-1 text-[11px] font-semibold text-go uppercase">{o.label}</span>
                    {o.name}
                    <div className="text-xs text-muted-foreground">
                      {unitsBothWays(o)}
                      {o.total_eur != null && ` · ${eur(o.total_eur)}`}
                      {o.available_date && ` · ${shortDate(o.available_date)}`}
                      {o.trade_off && ` · ${o.trade_off}`}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ),
        })
        break
      case 'decision': {
        const s = e.status ?? ''
        const person = s === 'approved' || s === 'rejected' || s === 'pending'
        const status = s === 'approved' ? 'confirmed' : s === 'pending' ? 'pending_approval' : s
        const lines = person
          ? [s === 'pending' ? 'Still waiting for your approval.' : `${s === 'approved' ? 'Approved' : 'Rejected'} by ${e.decided_by ?? 'you'}.`]
          : (e.reasons ?? [])
        out.push({
          id: e.id,
          side: 'left',
          who: 'Valio Aimo',
          icon: 'valio',
          time: e.ts,
          body: (
            <div className="space-y-1.5">
              <StatusBadge status={status} />
              {lines.map((r, i) => (
                <p key={i}>{r}</p>
              ))}
              <Alternatives items={e.alternatives} />
              {e.order_id && (
                <Link to={`/client/orders/${e.order_id}`} className="inline-block text-xs font-medium text-primary hover:underline">
                  Follow the delivery →
                </Link>
              )}
            </div>
          ),
        })
        break
      }
      case 'waiting':
        out.push({
          id: e.id,
          side: 'left',
          who: 'Valio Aimo',
          icon: 'valio',
          time: e.ts,
          body: (
            <span className="inline-flex items-center gap-1.5">
              <Hourglass className="size-4 text-wait" aria-hidden /> Waiting for your approval.{' '}
              <Link to="/client" className="font-medium text-primary hover:underline">
                Approve or reject
              </Link>
            </span>
          ),
        })
        break
      case 'run_end':
        if (e.summary) out.push({ id: e.id, side: 'left', who: 'Your agent', icon: 'agent', time: e.ts, body: e.summary })
        break
    }
  }
  return out
}

const AVATAR = {
  agent: { icon: Bot, cls: 'bg-secondary text-secondary-foreground' },
  valio: { icon: Building2, cls: 'bg-emphasis text-white' },
  buyer: { icon: UserRound, cls: 'bg-primary text-primary-foreground' },
}

export default function ClientChat() {
  const { buyerId, account } = useAccount()
  const { events } = useEvents(buyerId)
  const msgs = useMemo(() => toChat(events), [events])
  const box = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)

  useEffect(() => {
    if (pinned && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [msgs, pinned])

  return (
    <div className="flex h-[calc(100dvh-10rem)] flex-col md:h-[calc(100dvh-7rem)]">
      <div className="mb-3">
        <h1 className="text-[22px] font-semibold tracking-tight text-emphasis">Chat</h1>
        <p className="text-sm text-muted-foreground">What you asked {account ? `for ${account.name}` : ''}, and what your agent and Valio Aimo answered.</p>
      </div>
      <div className="relative min-h-0 flex-1 rounded-xl border bg-muted/30">
        <div
          ref={box}
          onScroll={() => {
            const el = box.current
            if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
          }}
          className="h-full space-y-4 overflow-y-auto p-4 sm:p-6"
          aria-live="polite"
        >
          {msgs.length === 0 && <p className="py-16 text-center text-sm text-muted-foreground">No conversation yet.</p>}
          {msgs.map((m) =>
            m.side === 'divider' ? (
              <div key={m.id} className="flex items-center gap-3 py-1 text-xs text-muted-foreground">
                <span className="h-px flex-1 bg-border" />
                <span className="text-center">
                  <span className="font-medium text-foreground/80">{m.text}</span>
                  {m.sub && <span className="block">{m.sub}</span>}
                </span>
                <span className="h-px flex-1 bg-border" />
              </div>
            ) : (
              <Bubble key={m.id} m={m} />
            ),
          )}
        </div>
        {!pinned && (
          <Button size="sm" className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-md" onClick={() => setPinned(true)}>
            <ArrowDown /> Latest
          </Button>
        )}
      </div>
      {buyerId && <AskBox buyerId={buyerId} />}
    </div>
  )
}

const EXAMPLES = ['I need 1,000 litres of lactose-free milk by Monday', 'We need 200 litres of lactose-free milk by Tuesday']

/** The order box: starts this account's agent on the server. Its replies arrive in the chat above. */
function AskBox({ buyerId }: { buyerId: string }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    const check = () =>
      api<{ running: boolean }>(accountPath(buyerId, '/ask'))
        .then((r) => live && setBusy(r.running))
        .catch(() => {})
    check()
    if (!busy) return () => void (live = false)
    const t = setInterval(check, 2500)
    return () => {
      live = false
      clearInterval(t)
    }
  }, [buyerId, busy])

  async function send(e: FormEvent) {
    e.preventDefault()
    const t = text.trim()
    if (!t || busy) return
    setError(null)
    try {
      await api(accountPath(buyerId, '/ask'), { method: 'POST', body: JSON.stringify({ text: t }) })
      setText('')
      setBusy(true)
    } catch (err) {
      setError(err instanceof ApiFailure ? err.message : 'Could not start your agent.')
      if (err instanceof ApiFailure && err.code === 'agent_busy') setBusy(true)
    }
  }

  return (
    <div className="mt-3 space-y-2">
      <form onSubmit={send} className="flex gap-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What should your agent order?"
          aria-label="What should your agent order?"
          maxLength={300}
          disabled={busy}
          className="h-10 bg-white"
        />
        <Button type="submit" className="h-10" disabled={busy || !text.trim()}>
          {busy ? <Loader2 className="animate-spin" /> : <Send />} {busy ? 'Working…' : 'Send'}
        </Button>
      </form>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!busy && !text && (
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" onClick={() => setText(x)} className="rounded-full border bg-white px-3 py-1 text-xs text-muted-foreground hover:text-foreground">
              {x}
            </button>
          ))}
        </div>
      )}
      {busy && <p className="text-xs text-muted-foreground">Your agent is working. If an order needs your approval, approve it on the Overview page.</p>}
    </div>
  )
}

function Bubble({ m }: { m: Extract<Msg, { side: 'left' | 'right' }> }) {
  const right = m.side === 'right'
  const A = AVATAR[m.icon]
  return (
    <div className={cn('flex items-end gap-2', right && 'flex-row-reverse')}>
      <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', A.cls)} aria-hidden>
        <A.icon className="size-4" />
      </span>
      <div className={cn('max-w-[80%] min-w-0', right && 'text-right')}>
        <div className="mb-1 text-[11px] text-muted-foreground">
          {m.who}
          {m.time && <span> · {timeOf(m.time).slice(0, 5)}</span>}
        </div>
        <div
          className={cn(
            'inline-block rounded-2xl px-3.5 py-2.5 text-left text-sm whitespace-pre-wrap',
            right ? 'rounded-br-md bg-primary text-primary-foreground' : 'rounded-bl-md border bg-white',
          )}
        >
          {m.body}
        </div>
      </div>
    </div>
  )
}
