import { useMemo, useState } from 'react'
import { PageHeader } from '@/components/common'
import { EventFeed } from '@/components/feed'
import { LiveDot } from '@/components/status'
import { Card } from '@/components/ui/card'
import { ALL_ACCOUNTS, useEvents, usePoll } from '@/lib/api'
import type { AdminClient } from '@/lib/types'
import { cn } from '@/lib/utils'

const KINDS = {
  all: { label: 'Everything', kinds: null as string[] | null },
  tools: { label: 'MCP tool calls', kinds: ['scene', 'run_start', 'tool_call', 'tool_result'] },
  decisions: { label: 'Decisions', kinds: ['scene', 'decision', 'waiting', 'verify'] },
  messages: { label: 'Agent messages', kinds: ['scene', 'user', 'agent', 'request', 'ask', 'answer', 'options', 'run_end', 'note'] },
}
type Kind = keyof typeof KINDS

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={cn(
        'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
        on ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted',
      )}
    >
      {children}
    </button>
  )
}

/** Every buyer agent's activity, live: what it says, every MCP call, every decision. */
export default function OpsActivity() {
  const { events, live } = useEvents(ALL_ACCOUNTS)
  const { data: clients } = usePoll<AdminClient[]>('/admin/clients', 10000)
  const [client, setClient] = useState<string>('all')
  const [kind, setKind] = useState<Kind>('all')

  const shown = useMemo(() => {
    const kinds = KINDS[kind].kinds
    return events.filter((e) => (client === 'all' || e.buyer === client) && (!kinds || kinds.includes(e.kind)))
  }, [events, client, kind])

  return (
    <div className="flex h-[calc(100dvh-8rem)] flex-col md:h-[calc(100dvh-6rem)]">
      <PageHeader
        eyebrow="Valio Aimo · Trade operations"
        title="Live agent activity"
        sub="Every buyer agent connected to the MCP server: its messages, its tool calls (→) and the server’s decisions."
        actions={<LiveDot live={live} />}
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Chip on={client === 'all'} onClick={() => setClient('all')}>
          All clients
        </Chip>
        {(clients ?? []).map((c) => (
          <Chip key={c.buyer_id} on={client === c.buyer_id} onClick={() => setClient(c.buyer_id)}>
            <span className={cn('mr-1 inline-block size-1.5 rounded-full align-middle', c.agent_running ? 'bg-go' : 'bg-muted-foreground/40')} />
            {c.name}
          </Chip>
        ))}
        <span className="mx-1 h-5 w-px bg-border" />
        {(Object.keys(KINDS) as Kind[]).map((k) => (
          <Chip key={k} on={kind === k} onClick={() => setKind(k)}>
            {KINDS[k].label}
          </Chip>
        ))}
      </div>
      <Card className="min-h-0 flex-1 gap-0 p-0">
        <EventFeed events={shown} className="h-full" emptyText="No agent activity yet. Run a demo scene or an agent." />
      </Card>
    </div>
  )
}
