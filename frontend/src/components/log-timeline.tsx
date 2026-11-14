import { Bot, Code2, Server, UserRound } from 'lucide-react'
import { useState } from 'react'
import { dateTime, shortHash } from '@/lib/format'
import type { LogEntry } from '@/lib/types'
import { cn } from '@/lib/utils'

function actorKind(actor: string, action: string): 'code' | 'person' | 'agent' | 'server' {
  if (actor === 'policy' || action.startsWith('decision:')) return 'code'
  if (actor.includes('@') || action.startsWith('approval:')) return 'person'
  if (actor.includes('agent')) return 'agent'
  return 'server'
}

const ACTOR = {
  code: { icon: Code2, cls: 'bg-emphasis text-background' },
  person: { icon: UserRound, cls: 'bg-wait-soft text-wait' },
  agent: { icon: Bot, cls: 'bg-secondary text-secondary-foreground' },
  server: { icon: Server, cls: 'bg-muted text-muted-foreground' },
}

function actionTone(action: string): string {
  if (action.endsWith('confirmed') || action.endsWith('approved')) return 'text-ok'
  if (action.endsWith('rejected')) return 'text-stop'
  if (action.endsWith('pending_approval')) return 'text-wait'
  if (action.endsWith('needs_clarification')) return 'text-ask'
  return 'text-foreground'
}

function Row({ e, broken }: { e: LogEntry; broken?: boolean }) {
  const [open, setOpen] = useState(false)
  const kind = actorKind(e.actor, e.action)
  const A = ACTOR[kind]
  return (
    <li className={cn('px-4 py-3 sm:px-5', broken && 'bg-stop-soft')}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-xs text-muted-foreground tnum">#{e.seq}</span>
        <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium', A.cls)}>
          <A.icon className="size-3" aria-hidden />
          {e.actor}
        </span>
        <span className={cn('font-mono text-xs font-semibold', actionTone(e.action))}>{e.action}</span>
        <span className="text-xs text-muted-foreground">{dateTime(e.time)}</span>
        <button
          onClick={() => setOpen(!open)}
          className="ml-auto rounded font-mono text-[11px] text-muted-foreground hover:text-foreground"
          aria-expanded={open}
          title="Show hashes"
        >
          {shortHash(e.hash)}
        </button>
      </div>
      <p className="mt-1 text-sm text-foreground/90">{e.reason}</p>
      {open && (
        <dl className="mt-2 grid gap-1 rounded-md bg-muted/50 p-2 font-mono text-[11px] break-all text-muted-foreground">
          <div>
            <dt className="inline font-semibold">prev_hash </dt>
            <dd className="inline">{e.prev_hash}</dd>
          </div>
          <div>
            <dt className="inline font-semibold">hash </dt>
            <dd className="inline">{e.hash}</dd>
          </div>
        </dl>
      )}
    </li>
  )
}

export function LogTimeline({ entries, brokenAt }: { entries: LogEntry[]; brokenAt?: number | null }) {
  if (entries.length === 0) return <div className="p-5 text-sm text-muted-foreground">No log entries.</div>
  return (
    <ol className="divide-y">
      {entries.map((e) => (
        <Row key={e.seq} e={e} broken={brokenAt != null && e.seq === brokenAt} />
      ))}
    </ol>
  )
}
