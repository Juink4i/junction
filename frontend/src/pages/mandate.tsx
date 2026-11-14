import { AlertTriangle, Ban, BadgeCheck, CalendarClock, Euro, Repeat, ShieldAlert, Tags, UserCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { AllergenChips, Chip, PageHeader, TagChips } from '@/components/common'
import { Card } from '@/components/ui/card'
import { useAccount } from '@/lib/account'
import { categoryName, eur, shortDate } from '@/lib/format'

function Rule({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3 py-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary text-secondary-foreground">{icon}</span>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-emphasis">{title}</div>
        <div className="text-sm text-muted-foreground">{children}</div>
      </div>
    </li>
  )
}

export default function MandatePage() {
  const { account } = useAccount()
  const m = account?.mandate
  if (!account) return null

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader eyebrow={account.name} title="Mandate" sub="What this account’s AI agent may do on its own, as rules the buyer signed." />
      <Card className="gap-0 p-5">
        <div className="flex flex-wrap items-center gap-2">
          {account.mandate_verified ? (
            <Chip tone="ok">
              <BadgeCheck className="size-3.5" /> Signed · Ed25519 · signature checked
            </Chip>
          ) : (
            <Chip tone="stop">
              <AlertTriangle className="size-3.5" /> {account.mandate_problem ?? 'Signature not valid'}
            </Chip>
          )}
          {m && <Chip>valid until {shortDate(m.valid_until)}</Chip>}
          {m && <span className="ml-auto font-mono text-[11px] text-muted-foreground">{m.mandate_id}</span>}
        </div>

        {m ? (
          <ul className="mt-2 divide-y">
            <Rule icon={<Euro className="size-4" />} title="Orders alone up to">
              {eur(m.auto_approve.max_order_eur)} per order and {eur(m.auto_approve.max_line_eur)} per line. Above that, a person approves.
            </Rule>
            <Rule icon={<Tags className="size-4" />} title="Allowed categories">
              {m.auto_approve.allowed_categories?.length ? m.auto_approve.allowed_categories.map(categoryName).join(', ') : 'Any category.'}
            </Rule>
            <Rule icon={<Repeat className="size-4" />} title="Substitutes">
              {m.substitution.allowed ? (
                <span className="inline-flex flex-wrap items-center gap-1">
                  Allowed, at most {m.substitution.max_price_increase_pct}% more per litre
                  {m.substitution.must_keep.length > 0 && (
                    <>
                      , and must stay <TagChips tags={m.substitution.must_keep} />
                    </>
                  )}
                  .
                </span>
              ) : (
                'Not allowed.'
              )}
            </Rule>
            <Rule icon={<Ban className="size-4" />} title="Blocked allergens">
              {m.hard_rules.blocked_allergens.length ? <AllergenChips codes={m.hard_rules.blocked_allergens} tone="stop" /> : 'None.'}
            </Rule>
            <Rule icon={<ShieldAlert className="size-4" />} title="Allergen info unknown">
              {m.hard_rules.unknown_allergens === 'human'
                ? 'Ask a person. Unknown is never treated as safe.'
                : m.hard_rules.unknown_allergens === 'reject'
                  ? 'Reject the order.'
                  : m.hard_rules.unknown_allergens}
            </Rule>
            <Rule icon={<CalendarClock className="size-4" />} title="Delivery">
              Must arrive by the need-by date. A missed order cut-off goes to a person.
            </Rule>
            <Rule icon={<UserCheck className="size-4" />} title="Approver">
              {m.approvers.join(', ')}
            </Rule>
          </ul>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">No mandate on file for this account.</p>
        )}
        <p className="mt-3 rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">
          These rules are enforced by the trade server’s code, not by the AI. The agent cannot change them, and this page only shows them.
        </p>
      </Card>
    </div>
  )
}
