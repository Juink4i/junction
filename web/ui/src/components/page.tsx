import type { ReactNode } from "react"
import { ShieldCheckIcon } from "lucide-react"
import { cn } from "@/lib/utils"

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm",
        className,
      )}
      aria-hidden
    >
      <ShieldCheckIcon className="size-5" />
    </span>
  )
}

/** Sticky page header: a title, a line under it, and whatever goes on the right. */
export function PageHeader({
  title,
  sub,
  right,
  width = "max-w-3xl",
  className,
}: {
  title: ReactNode
  sub?: ReactNode
  right?: ReactNode
  width?: string
  className?: string
}) {
  return (
    <header className={cn("sticky top-0 z-20 border-b bg-background/80 backdrop-blur-md", className)}>
      <div className={cn("mx-auto flex items-center gap-3 px-4 py-3", width)}>
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 text-[17px] leading-tight font-semibold tracking-tight">{title}</h1>
          {sub && <p className="mt-0.5 text-xs text-pretty text-muted-foreground">{sub}</p>}
        </div>
        {right}
      </div>
    </header>
  )
}
