import { ArrowRight, BadgeCheck, Building2 } from 'lucide-react'
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useParams } from 'react-router'
import { ClientShell } from '@/client/shell'
import ClientChat from '@/client/chat'
import ClientMandate from '@/client/mandate'
import ClientOverview from '@/client/overview'
import Onboarding from '@/client/onboarding'
import { OrderDetail } from '@/components/order-detail'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AccountProvider, useAccount } from '@/lib/account'
import { accountPath } from '@/lib/api'
import OpsActivity from '@/ops/activity'
import OpsAuditLog from '@/ops/audit-log'
import OpsDashboard from '@/ops/dashboard'
import OpsOrders from '@/ops/orders'
import { OpsShell } from '@/ops/shell'

function Landing() {
  const views = [
    {
      to: '/client',
      icon: BadgeCheck,
      title: 'Buyer',
      text: 'For a hotel, café or school kitchen: what your agent is doing, approvals, deliveries and your rules.',
    },
    {
      to: '/server',
      icon: Building2,
      title: 'Valio Aimo',
      text: 'Trade operations: every connected client, orders by stage, live agent activity and the full audit log.',
    },
  ]
  return (
    <div className="flex min-h-dvh items-center justify-center bg-white px-4 py-10">
      <div className="w-full max-w-3xl">
        <h1 className="text-center text-[28px] font-semibold tracking-tight text-emphasis">Trusted Trade</h1>
        <p className="mt-1 text-center text-sm text-muted-foreground">The AI suggests. Plain code decides. People approve the exceptions.</p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {views.map((v) => (
            <Link key={v.to} to={v.to} className="group rounded-xl border bg-white p-6 transition-colors hover:border-primary/50 hover:bg-secondary/30">
              <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <v.icon className="size-5" />
              </span>
              <div className="mt-4 flex items-center gap-1 text-lg font-semibold text-emphasis">
                {v.title} <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{v.text}</p>
            </Link>
          ))}
        </div>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          A new kitchen?{' '}
          <Link to="/onboarding" className="font-medium text-primary hover:underline">
            Set up your kitchen
          </Link>
        </p>
      </div>
    </div>
  )
}

function ClientLayout() {
  return (
    <AccountProvider>
      <ClientShell>
        <Outlet />
      </ClientShell>
    </AccountProvider>
  )
}

function ClientOrder() {
  const { orderId = '' } = useParams()
  const { buyerId } = useAccount()
  return <OrderDetail apiPath={buyerId ? accountPath(buyerId, `/orders/${orderId}`) : null} backTo="/client" backLabel="Overview" />
}

function OpsLayout() {
  return (
    <OpsShell>
      <Outlet />
    </OpsShell>
  )
}

function OpsOrder() {
  const { orderId = '' } = useParams()
  return <OrderDetail apiPath={`/admin/orders/${orderId}`} backTo="/server/orders" backLabel="Orders" withTrail />
}

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <TooltipProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/client" element={<ClientLayout />}>
            <Route index element={<ClientOverview />} />
            <Route path="chat" element={<ClientChat />} />
            <Route path="mandate" element={<ClientMandate />} />
            <Route path="orders/:orderId" element={<ClientOrder />} />
          </Route>
          <Route path="/server" element={<OpsLayout />}>
            <Route index element={<OpsDashboard />} />
            <Route path="orders" element={<OpsOrders />} />
            <Route path="orders/:orderId" element={<OpsOrder />} />
            <Route path="activity" element={<OpsActivity />} />
            <Route path="log" element={<OpsAuditLog />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster position="top-center" richColors />
      </TooltipProvider>
    </BrowserRouter>
  )
}
