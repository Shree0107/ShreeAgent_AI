import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { PlanCard } from '../components/plan/PlanCard'
import { SwingCard } from '../components/plan/SwingCard'
import { useNow } from '../components/TopBar'
import { api } from '../lib/api'
import { useLivePrice } from '../lib/live'
import { matchesFilter, plansApi, sortCards, type Account, type Filter, type PlanCard as Card } from '../lib/plans'
import { getSocket } from '../lib/ws'

type Mode = 'intraday' | 'swing'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'buy', label: 'Buy' }, { id: 'sell', label: 'Sell' },
  { id: 'ready', label: 'Get ready' }, { id: 'wait', label: 'Wait' },
]

const KEY = 'sa-plan'
function loadPrefs(): { mode?: Mode; filter?: Filter; account?: Account } {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}
function savePrefs(p: object) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    /* storage blocked: preferences just aren't remembered */
  }
}

function LiveCard({ card, now }: { card: Card; now: number }) {
  const live = useLivePrice(card.symbol)
  const fresh = live.price?.mid ?? null
  return <PlanCard card={card} price={fresh} feed={live.status} now={now} />
}

function SizeHelper({ value, onChange }: { value: Required<Account>; onChange: (a: Required<Account>) => void }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const apply = () => draft.account > 0 && draft.risk > 0 && onChange(draft)
  return (
    <form className="flex flex-wrap items-end gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); apply() }} aria-label="Position size helper">
      <label className="flex flex-col"><span className="text-xs text-muted">Account size</span>
        <input type="number" min={1} step="any" value={draft.account} onChange={(e) => setDraft({ ...draft, account: Number(e.target.value) })}
          className="w-28 rounded border border-line bg-panel-2 px-2 py-1" /></label>
      <label className="flex flex-col"><span className="text-xs text-muted">Risk per trade %</span>
        <input type="number" min={0.1} max={10} step={0.1} value={draft.risk} onChange={(e) => setDraft({ ...draft, risk: Number(e.target.value) })}
          className="w-20 rounded border border-line bg-panel-2 px-2 py-1" /></label>
      <label className="flex flex-col"><span className="text-xs text-muted">Currency</span>
        <select value={draft.ccy} onChange={(e) => setDraft({ ...draft, ccy: e.target.value })} className="rounded border border-line bg-panel-2 px-2 py-1">
          {['EUR', 'USD', 'GBP', 'CHF', 'PLN', 'INR'].map((c) => <option key={c}>{c}</option>)}
        </select></label>
      <button type="submit" className="rounded bg-accent px-3 py-1 text-white">Update sizes</button>
    </form>
  )
}

export default function TradePlanTab() {
  const prefs = useMemo(loadPrefs, [])
  const [mode, setMode] = useState<Mode>(prefs.mode ?? 'intraday')
  const [filter, setFilter] = useState<Filter>(prefs.filter ?? 'all')
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings, staleTime: 300_000 })
  const defaults = (settings.data?.account ?? {}) as { size?: number; risk_pct?: number; currency?: string }
  const [acct, setAcct] = useState<Account>(prefs.account ?? {})
  const account: Required<Account> = {
    account: acct.account ?? defaults.size ?? 1000, risk: acct.risk ?? defaults.risk_pct ?? 1, ccy: acct.ccy ?? defaults.currency ?? 'EUR',
  }
  useEffect(() => savePrefs({ mode, filter, account: acct }), [mode, filter, acct])
  const now = useNow(1000).getTime()
  const qc = useQueryClient()

  const plans = useQuery({
    queryKey: ['plans', account],
    queryFn: () => plansApi.plans(account),
    enabled: mode === 'intraday',
    refetchInterval: (q) => (q.state.data?.cards.some((c) => c.state === 'pending' || c.stale) ? 4000 : 30_000),
  })
  const swing = useQuery({ queryKey: ['swing', account], queryFn: () => plansApi.swing(account), enabled: mode === 'swing', refetchInterval: 60_000 })

  // Live refresh: a new card for a symbol, a finished plans job, or a status event -> refetch (sizes come from the server).
  const symbols = (plans.data?.cards ?? []).map((c) => c.symbol).join(',')
  useEffect(() => {
    if (mode !== 'intraday') return
    const s = getSocket()
    const refetch = () => qc.invalidateQueries({ queryKey: ['plans'] })
    const offs = symbols.split(',').filter(Boolean).map((sym) => s.on(`plan:${sym}`, refetch))
    offs.push(s.on('plan_event', refetch))
    offs.push(s.on('job', (d) => (d as { kind?: string }).kind === 'plans' && refetch()))
    return () => offs.forEach((o) => o())
  }, [symbols, mode, qc])

  const cards = sortCards(plans.data?.cards ?? []).filter((c) => matchesFilter(c, filter))

  return (
    <div className="mx-auto max-w-5xl space-y-3 p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded border border-line" role="group" aria-label="Mode">
          {([['intraday', 'Intraday (15 min)'], ['swing', 'Swing (daily)']] as const).map(([id, label]) => (
            <button key={id} type="button" aria-pressed={mode === id} onClick={() => setMode(id)}
              className={`px-3 py-1.5 text-sm ${mode === id ? 'bg-accent text-white' : 'text-muted hover:text-fg'}`}>{label}</button>
          ))}
        </div>
        {mode === 'intraday' && (
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filter">
            {FILTERS.map((f) => (
              <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}
                className={`rounded px-2.5 py-1 text-sm ${filter === f.id ? 'bg-panel-2 text-fg ring-1 ring-accent' : 'text-muted hover:text-fg'}`}>{f.label}</button>
            ))}
          </div>
        )}
      </div>
      <SizeHelper value={account} onChange={(a) => setAcct(a)} />

      {mode === 'intraday' ? (
        <>
          {plans.isLoading && <p className="text-muted">Loading trade plans…</p>}
          {plans.error && <p className="text-down">Could not load the trade plans: {(plans.error as Error).message}</p>}
          {plans.data && !cards.length && <p className="text-muted">No cards match this filter.</p>}
          <div className="grid gap-3">
            {cards.map((c) => <LiveCard key={c.symbol} card={c} now={now} />)}
          </div>
          {plans.data?.config && (
            <p className="text-xs text-muted">Same-day trades only: no new entries after {plans.data.config.no_new_entries_after}, everything closed by{' '}
              {plans.data.config.flat_by} ({(plans.data.config.timezone ?? 'Europe/Berlin').split('/').pop()} time). Plans update at every 15-minute candle close.</p>
          )}
        </>
      ) : (
        <div className="grid gap-3">
          {swing.isLoading && <p className="text-muted">Loading daily signals…</p>}
          {swing.error && <p className="text-down">Could not load the daily signals: {(swing.error as Error).message}</p>}
          {(swing.data?.cards ?? []).map((c) => <SwingCard key={c.symbol} card={c} />)}
        </div>
      )}
    </div>
  )
}
