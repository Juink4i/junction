import { BadgeCheck, Building2, LayoutDashboard, MessagesSquare, ShieldCheck, Truck } from 'lucide-react'
import { useLayoutEffect, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useAccount } from '@/lib/account'
import { cn } from '@/lib/utils'
import { usePendingCount } from './use-pending'

const TABS = [
  { to: '/client', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/client/deliveries', label: 'Deliveries', icon: Truck, end: false },
  { to: '/client/chat', label: 'Chat', icon: MessagesSquare, end: false },
  { to: '/client/mandate', label: 'Mandate', icon: ShieldCheck, end: false },
]

/** The buyer's app: white, light, three tabs. Kept deliberately simple. */
export function ClientShell({ children }: { children: ReactNode }) {
  const { accounts, account, buyerId, setBuyerId, error } = useAccount()
  const pending = usePendingCount(buyerId)

  // The client view is always light on white.
  useLayoutEffect(() => {
    const root = document.documentElement
    const wasDark = root.classList.contains('dark')
    root.classList.remove('dark')
    return () => {
      if (wasDark) root.classList.add('dark')
    }
  }, [])

  return (
    <div className="min-h-dvh bg-white text-foreground">
      <header className="sticky top-0 z-20 border-b bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4">
          <Link to="/client" className="flex shrink-0 items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BadgeCheck className="size-4.5" />
            </span>
            <span className="hidden text-sm font-semibold text-emphasis sm:block">Trusted Trade</span>
          </Link>
          <nav className="ml-2 hidden items-center gap-1 md:flex" aria-label="Main">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  cn(
                    'relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    isActive ? 'bg-secondary text-secondary-foreground' : 'text-muted-foreground hover:text-foreground',
                  )
                }
              >
                {t.label}
                {t.to === '/client' && pending > 0 && (
                  <span className="ml-1.5 rounded-full bg-wait px-1.5 text-[10px] leading-4 text-white">{pending}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto min-w-0">
            <Select value={buyerId ?? undefined} onValueChange={setBuyerId}>
              <SelectTrigger className="h-9 w-full min-w-0 bg-white sm:w-64" aria-label="Account">
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
          </div>
          <div className="shrink-0">
            <Link to="/onboarding" className="hidden text-sm font-medium text-primary hover:underline sm:inline" title="Sign up another kitchen">
              + New kitchen
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 pt-6 pb-24 md:pb-12">
        {error && !account ? (
          <div className="rounded-lg border border-stop/25 bg-stop-soft p-4 text-sm text-stop">{error}</div>
        ) : (
          children
        )}
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t bg-white md:hidden" aria-label="Main">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              cn('relative flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium', isActive ? 'text-primary' : 'text-muted-foreground')
            }
          >
            <t.icon className="size-5" aria-hidden />
            {t.label}
            {t.to === '/client' && pending > 0 && (
              <span className="absolute top-1 right-[calc(50%-20px)] rounded-full bg-wait px-1.5 text-[10px] leading-4 text-white">{pending}</span>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
