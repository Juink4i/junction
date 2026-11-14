import { ChatFeed } from "@/components/chat-feed"
import { PageHeader } from "@/components/page"
import { ActorPill, LinkDot } from "@/components/status"
import { useEventStream } from "@/lib/events"
import { mount } from "@/lib/mount"

function ChatPage() {
  const { events, link } = useEventStream()
  return (
    <div className="flex h-dvh flex-col">
      <PageHeader
        title="Agent conversation"
        sub={
          <span className="inline-flex flex-wrap items-center gap-1">
            What the buyer agent says and does, live. <ActorPill actor="ai" /> suggests, <ActorPill actor="code" /> decides.
          </span>
        }
        right={<LinkDot state={link} labels={{ offline: "reconnecting" }} />}
      />
      <ChatFeed events={events} className="flex-1" inner="mx-auto w-full max-w-3xl" />
    </div>
  )
}

mount(<ChatPage />)
