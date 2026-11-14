import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AppShell } from '@/components/shell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AccountProvider } from '@/lib/account'
import ActivityPage from '@/pages/activity'
import ApprovalsPage from '@/pages/approvals'
import AuditLogPage from '@/pages/audit-log'
import MandatePage from '@/pages/mandate'
import OrderDetailPage from '@/pages/order-detail'
import OrdersPage from '@/pages/orders'
import OverviewPage from '@/pages/overview'

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <TooltipProvider>
        <AccountProvider>
          <AppShell>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/approvals" element={<ApprovalsPage />} />
              <Route path="/orders" element={<OrdersPage />} />
              <Route path="/orders/:orderId" element={<OrderDetailPage />} />
              <Route path="/log" element={<AuditLogPage />} />
              <Route path="/mandate" element={<MandatePage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AppShell>
          <Toaster position="top-center" richColors />
        </AccountProvider>
      </TooltipProvider>
    </BrowserRouter>
  )
}
