import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, usePoll } from './api'
import type { Account } from './types'

interface AccountState {
  accounts: Account[]
  account: Account | null
  buyerId: string | null
  setBuyerId: (id: string) => void
  follow: boolean
  setFollow: (on: boolean) => void
  error: string | null
}

const Ctx = createContext<AccountState | null>(null)
const KEY = 'tt.account'
const FOLLOW_KEY = 'tt.follow'

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* storage blocked: fine, just not remembered */
  }
}

export function AccountProvider({ children }: { children: ReactNode }) {
  const { data, error } = usePoll<Account[]>('/accounts', 30000)
  const accounts = useMemo(() => data ?? [], [data])
  const fromUrl = new URLSearchParams(window.location.search).get('account')
  const [buyerId, setBuyer] = useState<string | null>(fromUrl ?? read(KEY))
  const [follow, setFollowState] = useState(read(FOLLOW_KEY) === '1')

  const setBuyerId = (id: string) => {
    setBuyer(id)
    write(KEY, id)
  }
  const setFollow = (on: boolean) => {
    setFollowState(on)
    write(FOLLOW_KEY, on ? '1' : '0')
  }

  // Default to the first account once the list arrives.
  useEffect(() => {
    if (accounts.length && !accounts.some((a) => a.buyer_id === buyerId)) setBuyer(accounts[0].buyer_id)
  }, [accounts, buyerId])

  // "Follow the demo": switch to whichever account the running scene belongs to.
  useEffect(() => {
    if (!follow) return
    let alive = true
    const check = () =>
      api<{ active_buyer?: string | null }>('/info')
        .then((info) => {
          if (alive && info.active_buyer) setBuyer(info.active_buyer)
        })
        .catch(() => {})
    check()
    const t = window.setInterval(check, 2000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [follow])

  const account = accounts.find((a) => a.buyer_id === buyerId) ?? null
  const value: AccountState = {
    accounts,
    account,
    buyerId: account?.buyer_id ?? null,
    setBuyerId,
    follow,
    setFollow,
    error: error?.message ?? null,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAccount(): AccountState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAccount outside AccountProvider')
  return v
}
