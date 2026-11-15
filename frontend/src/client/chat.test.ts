import { describe, expect, it } from 'vitest'
import type { AgentEvent } from '@/lib/types'
import { toChat } from './chat'

let id = 0
const ev = (kind: string, extra: Partial<AgentEvent> = {}): AgentEvent => ({
  id: ++id,
  kind,
  run_id: 'r1',
  ts: '2026-11-15T06:56:26.405+00:00',
  ...extra,
})

const agentTexts = (events: AgentEvent[]) => toChat(events).flatMap((m) => ('body' in m && m.who === 'Your agent' ? [m.body] : []))

describe('toChat', () => {
  it('shows the final message once, not again as the run summary', () => {
    const text = 'Please confirm if delivery on Monday is acceptable.'
    expect(agentTexts([ev('run_start'), ev('agent', { text }), ev('run_end', { summary: text })])).toEqual([text])
  })

  it('still shows a summary the agent did not already say', () => {
    expect(agentTexts([ev('run_start'), ev('run_end', { summary: 'Stopped.' })])).toEqual(['Stopped.'])
  })
})
