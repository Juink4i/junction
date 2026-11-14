import "@fontsource-variable/jetbrains-mono"
import "@/index.css"

import { StrictMode, type ReactNode } from "react"
import { createRoot } from "react-dom/client"
import { TooltipProvider } from "@/components/ui/tooltip"

/** Render one page into #root. Follows the system's light or dark setting live. */
export function mount(page: ReactNode) {
  const dark = matchMedia("(prefers-color-scheme: dark)")
  const apply = () => document.documentElement.classList.toggle("dark", dark.matches)
  apply()
  dark.addEventListener("change", apply)
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <TooltipProvider delayDuration={200}>{page}</TooltipProvider>
    </StrictMode>,
  )
}
