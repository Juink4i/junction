import type { ReactNode } from "react"

// Tiny Markdown for agent messages: **bold**, `code`, "- " bullets, "# " headings, line breaks.
// It builds React elements, so nothing the agent writes is ever read as HTML.

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    if (m[1] !== undefined) out.push(<strong key={m.index} className="font-semibold">{m[1]}</strong>)
    else
      out.push(
        <code key={m.index} className="rounded bg-black/5 px-1 py-px font-mono text-[0.86em] dark:bg-white/10">
          {m[2]}
        </code>,
      )
    last = re.lastIndex
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Markdown({ text }: { text?: string | null }) {
  const blocks: ReactNode[] = []
  let list: ReactNode[] = []
  const flush = () => {
    if (list.length) blocks.push(<ul key={`ul${blocks.length}`} className="my-1 list-disc space-y-0.5 pl-5">{list}</ul>)
    list = []
  }
  String(text ?? "")
    .split(/\r?\n/)
    .forEach((line, i) => {
      const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/)
      const heading = line.match(/^\s*#{1,6}\s+(.*)$/)
      if (bullet) {
        list.push(<li key={i}>{inline(bullet[1])}</li>)
        return
      }
      flush()
      if (heading) blocks.push(<p key={i} className="font-semibold">{inline(heading[1])}</p>)
      else if (line.trim()) blocks.push(<p key={i}>{inline(line)}</p>)
    })
  flush()
  return <div className="space-y-1.5 leading-relaxed">{blocks}</div>
}
