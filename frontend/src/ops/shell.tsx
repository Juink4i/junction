import { Activity, Building2, LayoutDashboard, Moon, Package, ScrollText, Sun } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router'
import { LogIntactBadge } from '@/components/status'
import { Button } from '@/components/ui/button'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { usePoll } from '@/lib/api'
import type { AdminOrder } from '@/lib/types'
import { cn } from '@/lib/utils'
import { RangeProvider } from './range'

const NAV = [
  { to: '/server', label: 'Dashboard', short: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/server/orders', label: 'Orders', short: 'Orders', icon: Package, end: false },
  { to: '/server/activity', label: 'Live agent activity', short: 'Live', icon: Activity, end: false },
  { to: '/server/log', label: 'Audit log', short: 'Log', icon: ScrollText, end: false },
]

function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem('tt.theme')
      if (saved) return saved === 'dark'
    } catch {
      /* ignore */
    }
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    return () => document.documentElement.classList.remove('dark')
  }, [dark])
  return [
    dark,
    () =>
      setDark((d) => {
        try {
          localStorage.setItem('tt.theme', d ? 'light' : 'dark')
        } catch {
          /* ignore */
        }
        return !d
      }),
  ]
}

/** Orders waiting on a buyer (input or approval), across every client. */
export function useOpenCount(): number {
  const { data } = usePoll<AdminOrder[]>('/admin/orders', 5000)
  return (data ?? []).filter((o) => o.status === 'pending_approval' || o.status === 'needs_clarification').length
}

/** Valio Aimo's operations app: every client, every agent, the whole log. */
export function OpsShell({ children }: { children: ReactNode }) {
  const [dark, toggleTheme] = useTheme()
  const open = useOpenCount()
  const loc = useLocation()

  return (
    <RangeProvider>
      <SidebarProvider>
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <Link to="/server" className="flex items-center gap-2 px-1 py-1.5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-emphasis text-background">
                <Building2 className="size-4.5" />
              </span>
              <div className="min-w-0 group-data-[collapsible=icon]:hidden">
                <div className="truncate text-sm font-semibold text-emphasis">Valio Aimo</div>
                <div className="truncate text-[11px] text-muted-foreground">Trade operations</div>
              </div>
            </Link>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupLabel>Operations</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {NAV.map((n) => {
                    const active = n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)
                    return (
                      <SidebarMenuItem key={n.to}>
                        <SidebarMenuButton asChild isActive={active} tooltip={n.label}>
                          <NavLink to={n.to} end={n.end}>
                            <n.icon />
                            <span>{n.label}</span>
                          </NavLink>
                        </SidebarMenuButton>
                        {n.to === '/server/orders' && open > 0 && (
                          <SidebarMenuBadge className="bg-wait-soft text-wait">{open}</SidebarMenuBadge>
                        )}
                      </SidebarMenuItem>
                    )
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter>
            <div className="rounded-lg border bg-card p-3 text-xs group-data-[collapsible=icon]:hidden">
              <div className="font-semibold text-emphasis">The AI suggests.</div>
              <div className="text-muted-foreground">Plain code decides. People approve the exceptions.</div>
            </div>
          </SidebarFooter>
        </Sidebar>

        <SidebarInset className="min-w-0">
          <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/90 px-3 backdrop-blur sm:px-6">
            <SidebarTrigger className="hidden md:inline-flex" />
            <span className="text-sm font-semibold text-emphasis md:hidden">Valio Aimo · Operations</span>
            <span className="ml-auto" />
            <LogIntactBadge />
            <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={dark ? 'Light mode' : 'Dark mode'}>
              {dark ? <Sun /> : <Moon />}
            </Button>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-5 pb-24 sm:px-6 md:pb-10">{children}</main>
        </SidebarInset>

        <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t bg-card/95 backdrop-blur md:hidden" aria-label="Main">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cn('relative flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium', isActive ? 'text-primary' : 'text-muted-foreground')
              }
            >
              <n.icon className="size-5" aria-hidden />
              {n.short}
            </NavLink>
          ))}
        </nav>
      </SidebarProvider>
    </RangeProvider>
  )
}
