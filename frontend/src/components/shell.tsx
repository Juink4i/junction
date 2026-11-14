import { Activity, BadgeCheck, Building2, ClipboardCheck, LayoutDashboard, Moon, Package, ScrollText, ShieldCheck, Sun } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { accountPath, usePoll } from '@/lib/api'
import { useAccount } from '@/lib/account'
import type { PendingApproval } from '@/lib/types'
import { cn } from '@/lib/utils'
import { LogIntactBadge } from './status'

const NAV = [
  { to: '/', label: 'Overview', short: 'Live', icon: LayoutDashboard },
  { to: '/activity', label: 'Agent activity', short: 'Activity', icon: Activity },
  { to: '/approvals', label: 'Approvals', short: 'Approve', icon: ClipboardCheck },
  { to: '/orders', label: 'Orders & delivery', short: 'Orders', icon: Package },
  { to: '/log', label: 'Audit log', short: 'Log', icon: ScrollText },
  { to: '/mandate', label: 'Mandate', short: 'Mandate', icon: ShieldCheck },
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

export function usePendingCount(): number {
  const { buyerId } = useAccount()
  const { data } = usePoll<PendingApproval[]>(buyerId ? accountPath(buyerId, '/approvals') : null, 3000)
  return data?.length ?? 0
}

function AccountSwitcher({ className }: { className?: string }) {
  const { accounts, buyerId, setBuyerId, follow, setFollow } = useAccount()
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <Select
        value={buyerId ?? undefined}
        onValueChange={(v) => {
          setFollow(false)
          setBuyerId(v)
        }}
      >
        <SelectTrigger className="h-9 w-full min-w-0 bg-card sm:w-72" aria-label="Account">
          <Building2 className="size-4 text-muted-foreground" />
          <SelectValue placeholder="Choose an account" />
        </SelectTrigger>
        <SelectContent>
          {accounts.map((a) => (
            <SelectItem key={a.buyer_id} value={a.buyer_id}>
              {a.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <label className="hidden shrink-0 cursor-pointer items-center gap-1.5 text-xs text-muted-foreground md:flex" title="Switch account automatically to the one the running demo scene uses">
        <input type="checkbox" className="accent-[var(--primary)]" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
        Follow demo
      </label>
    </div>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const [dark, toggleTheme] = useTheme()
  const pending = usePendingCount()
  const { account, error } = useAccount()
  const loc = useLocation()

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center gap-2 px-1 py-1.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BadgeCheck className="size-4.5" />
            </span>
            <div className="min-w-0 group-data-[collapsible=icon]:hidden">
              <div className="truncate text-sm font-semibold text-emphasis">Trusted Trade</div>
              <div className="truncate text-[11px] text-muted-foreground">for Valio Aimo</div>
            </div>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Account view</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map((n) => {
                  const active = n.to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(n.to)
                  return (
                    <SidebarMenuItem key={n.to}>
                      <SidebarMenuButton asChild isActive={active} tooltip={n.label}>
                        <NavLink to={n.to} end={n.to === '/'}>
                          <n.icon />
                          <span>{n.label}</span>
                        </NavLink>
                      </SidebarMenuButton>
                      {n.to === '/approvals' && pending > 0 && (
                        <SidebarMenuBadge className="bg-wait-soft text-wait">{pending}</SidebarMenuBadge>
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
          <AccountSwitcher className="min-w-0 flex-1" />
          <LogIntactBadge className="hidden sm:inline-flex" />
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={dark ? 'Light mode' : 'Dark mode'}>
            {dark ? <Sun /> : <Moon />}
          </Button>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-5 pb-24 sm:px-6 md:pb-10">
          {error && !account ? (
            <div className="rounded-lg border border-stop/25 bg-stop-soft p-4 text-sm text-stop">
              {error} Is <code>uv run python -m web</code> running?
            </div>
          ) : (
            children
          )}
        </main>
      </SidebarInset>

      {/* Bottom tab bar on phones */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t bg-card/95 backdrop-blur md:hidden" aria-label="Main">
        {NAV.filter((n) => n.to !== '/mandate').map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) =>
              cn('relative flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium', isActive ? 'text-primary' : 'text-muted-foreground')
            }
          >
            <n.icon className="size-5" aria-hidden />
            {n.short}
            {n.to === '/approvals' && pending > 0 && (
              <span className="absolute top-1 right-[calc(50%-18px)] rounded-full bg-wait px-1.5 text-[10px] leading-4 text-white">{pending}</span>
            )}
          </NavLink>
        ))}
      </nav>
    </SidebarProvider>
  )
}
