import type { ComponentProps, ReactNode } from "react"
import {
  BanIcon,
  BotIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  CpuIcon,
  HourglassIcon,
  SparklesIcon,
  UserCheckIcon,
  UserRoundIcon,
  type LucideIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { LinkState } from "@/lib/events"

// The visual language every screen shares: what the AI did, what code decided, what a
// person decided. Each has its own colour and icon, on purpose.

export type Tone = "success" | "warning" | "info" | "danger" | "code" | "brand" | "neutral"

export const toneClass: Record<Tone, string> = {
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  info: "bg-info-soft text-info",
  danger: "bg-destructive-soft text-destructive",
  code: "bg-code-soft text-code",
  brand: "bg-brand-soft text-brand",
  neutral: "bg-muted text-muted-foreground",
}

export const toneText: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  info: "text-info",
  danger: "text-destructive",
  code: "text-code",
  brand: "text-brand",
  neutral: "text-muted-foreground",
}

export const toneBorder: Record<Tone, string> = {
  success: "border-success/60",
  warning: "border-warning/60",
  info: "border-info/60",
  danger: "border-destructive/60",
  code: "border-code/60",
  brand: "border-brand/60",
  neutral: "border-border",
}

export function Pill({
  tone = "neutral",
  icon: Icon,
  className,
  children,
  ...props
}: { tone?: Tone; icon?: LucideIcon; children: ReactNode } & ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-full px-2 text-[11px] font-semibold whitespace-nowrap",
        toneClass[tone],
        className,
      )}
      {...props}
    >
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  )
}

export interface StatusMeta {
  tone: Tone
  icon: LucideIcon
  label: string
}

export const STATUS: Record<string, StatusMeta> = {
  confirmed: { tone: "success", icon: CircleCheckIcon, label: "Confirmed" },
  approved: { tone: "success", icon: CircleCheckIcon, label: "Approved by a person" },
  pending_approval: { tone: "warning", icon: UserRoundIcon, label: "Needs a person's approval" },
  pending: { tone: "warning", icon: HourglassIcon, label: "Still waiting for approval" },
  needs_clarification: { tone: "info", icon: CircleHelpIcon, label: "Server asks the agent to confirm" },
  rejected: { tone: "danger", icon: BanIcon, label: "Rejected" },
}

export const statusMeta = (s?: string): StatusMeta =>
  STATUS[s ?? ""] ?? { tone: "neutral", icon: CircleHelpIcon, label: s ?? "unknown" }

/** Who did it: the AI, the server's plain code, or a person. */
export type Actor = "ai" | "mcp" | "code" | "person"

export const ACTOR: Record<Actor, { tone: Tone; icon: LucideIcon; label: string }> = {
  ai: { tone: "brand", icon: SparklesIcon, label: "AI" },
  mcp: { tone: "neutral", icon: BotIcon, label: "MCP" },
  code: { tone: "code", icon: CpuIcon, label: "code" },
  person: { tone: "success", icon: UserCheckIcon, label: "person" },
}

export function ActorPill({ actor, children, className }: { actor: Actor; children?: ReactNode; className?: string }) {
  const a = ACTOR[actor]
  return (
    <Pill tone={a.tone} icon={a.icon} className={className}>
      {children ?? a.label}
    </Pill>
  )
}

/** Live / offline dot for pages that poll or stream. */
export function LinkDot({ state, labels }: { state: LinkState; labels?: Partial<Record<LinkState, string>> }) {
  const text = { connecting: "connecting", live: "live", offline: "offline", ...labels }[state]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-muted-foreground" role="status">
      <span className="relative flex size-2">
        {state === "live" && <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-50" />}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            state === "live" ? "bg-success" : state === "offline" ? "bg-destructive" : "bg-muted-foreground/50",
          )}
        />
      </span>
      {text}
    </span>
  )
}
