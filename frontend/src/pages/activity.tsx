import { useMemo, useState } from 'react'
import { PageHeader } from '@/components/common'
import { EventFeed } from '@/components/feed'
import { LiveDot } from '@/components/status'
import { Card } from '@/components/ui/card'
import { useAccount } from '@/lib/account'
import { useEvents } from '@/lib/api'
import { cn } from '@/lib/utils'

const FILTERS = {
  all: { label: 'All', kinds: null as string[] | null },
  messages: { label: 'Messages', kinds: ['scene', 'user', 'agent', 'request', 'ask', 'answer', 'options', 'run_end', 'note'] },
  tools: { label: 'Tool calls', kinds: ['scene', 'tool_call', 'tool_result'] },
  decisions: { label: 'Decisions', kinds: ['scene', 'decision', 'waiting', 'verify'] },
}
type Key = keyof typeof FILTERS

export default function ActivityPage() {
  const { buyerId, account } = useAccount()
  const { events, live } = useEvents(buyerId)
  const [filter, setFilter] = useState<Key>('all')
  const shown = useMemo(() => {
    const kinds = FILTERS[filter].kinds
    return kinds ? events.filter((e) => kinds.includes(e.kind)) : events
  }, [events, filter])

  return (
    <div className="flex h-[calc(100dvh-8rem)] flex-col md:h-[calc(100dvh-6rem)]">
      <PageHeader
        eyebrow={account?.name}
        title="Agent activity"
        sub="What this account's buyer agent says (bubbles), what it asks the server (→ tool calls), and what the server decides (banners)."
        actions={<LiveDot live={live} />}
      />
      <div className="mb-3 flex flex-wrap gap-2" role="tablist">
        {(Object.keys(FILTERS) as Key[]).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={filter === k}
            onClick={() => setFilter(k)}
            className={cn(
              'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
              filter === k ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted',
            )}
          >
            {FILTERS[k].label}
          </button>
        ))}
      </div>
      <Card className="min-h-0 flex-1 gap-0 p-0">
        <EventFeed events={shown} className="h-full" emptyText="No agent activity for this account yet. Run a demo scene or the agent." />
      </Card>
    </div>
  )
}
