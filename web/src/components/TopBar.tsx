import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, type SymbolInfo } from '../lib/api'
import { decimalsFor, fmtPct, fmtPrice } from '../lib/format'
import { sessionLabel } from '../lib/sessions'
import { useApp } from '../lib/store'
import { describeStatus, useLivePrice } from '../lib/live'
import { AlertsBell } from './AlertsBell'
import { useConnection } from '../lib/ws'

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v)
  useEffect(() => {
    const id = setTimeout(() => setD(v), ms)
    return () => clearTimeout(id)
  }, [v, ms])
  return d
}

export function useNow(ms = 1000): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

function Search() {
  const setSymbol = useApp((s) => s.setSymbol)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const dq = useDebounced(q.trim(), 300)
  const { data = [], isFetching } = useQuery({ queryKey: ['search', dq], queryFn: () => api.search(dq), enabled: dq.length >= 2 })
  const pick = (s: SymbolInfo) => {
    setSymbol(s.ticker)
    setQ('')
    setOpen(false)
  }
  return (
    <div className="relative w-full max-w-64">
      <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => e.key === 'Enter' && data[0] && pick(data[0])}
        placeholder="🔍 Search: EUR/USD, Apple, SAP…" aria-label="Search symbol"
        className="w-full rounded-md border border-line bg-panel-2 px-3 py-1.5 text-sm outline-none placeholder:text-muted focus:border-accent" />
      {open && dq.length >= 2 && (
        <div className="absolute left-0 right-0 top-9 z-40 max-h-80 overflow-auto rounded-md border border-line bg-panel shadow-xl">
          {isFetching && <div className="px-3 py-2 text-xs text-muted">Searching…</div>}
          {!isFetching && data.length === 0 && <div className="px-3 py-2 text-xs text-muted">No matches</div>}
          {data.map((s) => (
            <button key={s.ticker} onMouseDown={() => pick(s)} className="flex w-full items-baseline gap-2 px-3 py-2 text-left hover:bg-panel-2">
              <span className="font-semibold">{s.ticker}</span>
              <span className="truncate text-xs text-muted">{s.name} · {s.market}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Watchlist() {
  const { symbol, setSymbol } = useApp()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { data: list = [] } = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const refresh = (l: string[]) => qc.setQueryData(['watchlist'], l)
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const inList = list.includes(symbol)
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-sm font-semibold hover:bg-panel-2">
        ★ {symbol} <span className="text-muted">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-10 z-40 w-60 rounded-md border border-line bg-panel p-1 shadow-xl">
          <div className="px-2 py-1 text-xs uppercase tracking-wide text-muted">Watchlist</div>
          {list.map((s) => (
            <div key={s} className={`flex items-center rounded ${s === symbol ? 'bg-panel-2' : ''}`}>
              <button className="flex-1 px-2 py-1.5 text-left text-sm hover:text-accent" onClick={() => { setSymbol(s); setOpen(false) }}>{s}</button>
              <button title={`Remove ${s}`} className="px-2 text-muted hover:text-down" onClick={() => api.removeFromWatchlist(s).then(refresh)}>✕</button>
            </div>
          ))}
          {!inList && (
            <button className="mt-1 w-full rounded px-2 py-1.5 text-left text-sm text-accent hover:bg-panel-2"
              onClick={() => api.addToWatchlist(symbol).then(refresh)}>＋ Add {symbol}</button>
          )}
        </div>
      )}
    </div>
  )
}

const TONE = { up: 'bg-up', wait: 'bg-wait', down: 'bg-down', muted: 'bg-muted' } as const

function StatusDot({ status, source }: { status: Parameters<typeof describeStatus>[1]; source: string }) {
  const conn = useConnection((s) => s.state)
  const v = describeStatus(conn, status, source)
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted" title={v.help} data-testid="status-dot">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${TONE[v.tone]} ${v.pulse ? 'animate-pulse' : ''}`} />{v.label}
    </span>
  )
}

export function TopBar({ onAskAI }: { onAskAI: () => void }) {
  const { symbol, theme, toggleTheme } = useApp()
  const now = useNow(30_000)
  const { data: q } = useQuery({ queryKey: ['quote', symbol], queryFn: () => api.quote(symbol), refetchInterval: 60_000 })
  const live = useLivePrice(symbol)
  const dec = decimalsFor(symbol, q?.price)
  // % change keeps the quote's base (previous day close) but follows the live price.
  const base = q ? q.price / (1 + q.change_pct / 100) : null
  const price = live.price?.mid ?? q?.price
  const chg = price !== undefined && base ? (price / base - 1) * 100 : q?.change_pct
  const status = live.status ?? (q?.source === 'oanda' ? 'live' : 'delayed')
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-3 py-2">
      <div className="flex items-center gap-2 font-bold tracking-tight"><span className="text-accent">◆</span> ShreeAgent AI</div>
      <Search />
      <Watchlist />
      <div className="num flex items-baseline gap-2">
        <span className={`text-lg font-semibold ${status === 'stale' ? 'text-muted line-through' : ''}`} data-testid="top-price">
          {price !== undefined ? fmtPrice(price, dec) : '…'}
        </span>
        {chg !== undefined && <span className={chg >= 0 ? 'text-up' : 'text-down'}>{chg >= 0 ? '▲' : '▼'} {fmtPct(chg)}</span>}
        {live.price?.spread_pips != null && <span className="text-xs text-muted" title="Current spread">spread {live.price.spread_pips.toFixed(1)} pips</span>}
      </div>
      <span className="text-xs text-muted">{sessionLabel(now)}</span>
      <div className="ml-auto flex items-center gap-3">
        <StatusDot status={status} source={live.price?.source ?? q?.source ?? ''} />
        <AlertsBell />
        <button onClick={toggleTheme} title="Switch light / dark" className="rounded-md border border-line px-2 py-1 text-sm">
          {theme === 'dark' ? '☀' : '🌙'}
        </button>
        <button onClick={onAskAI} className="rounded-md bg-accent px-3 py-1 text-sm font-semibold text-white">Ask AI</button>
      </div>
    </header>
  )
}
