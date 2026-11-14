// Live prices and feed status pushed by the backend over the WebSocket.
import { useEffect } from 'react'
import { create } from 'zustand'
import type { Candle } from './api'
import { getSocket, useConnection } from './ws'

export interface LivePrice {
  symbol: string
  bid: number | null
  ask: number | null
  mid: number | null
  ts: number | null // unix seconds of the price
  spread_pips: number | null
  source: string // 'oanda' (real time) | 'yfinance' (delayed) | ...
  status: SymbolStatus
}

export type SymbolStatus = 'starting' | 'live' | 'delayed' | 'stale' | 'closed' | 'error'

interface LiveStore {
  prices: Record<string, LivePrice>
  statuses: Record<string, SymbolStatus>
  feeds: Record<string, { state: string; detail: string }>
  oandaConfigured: boolean
  lastUpdate: Record<string, number> // client time (ms) of the last message per symbol
}

export const useLive = create<LiveStore>(() => ({ prices: {}, statuses: {}, feeds: {}, oandaConfigured: false, lastUpdate: {} }))

let wired = false
/** Subscribe once to the global status topic. */
export function wireLiveStatus() {
  if (wired) return
  wired = true
  getSocket().on('status', (d) => {
    const s = d as { feeds: LiveStore['feeds']; symbols: Record<string, LivePrice>; oanda_configured: boolean }
    useLive.setState((st) => {
      const statuses = { ...st.statuses }
      const prices = { ...st.prices }
      for (const [k, v] of Object.entries(s.symbols ?? {})) {
        statuses[k] = v.status
        if (v.mid !== null) prices[k] = v
      }
      return { feeds: s.feeds ?? {}, statuses, prices, oandaConfigured: !!s.oanda_configured }
    })
  })
}

/** Live price + status for one symbol (subscribes while mounted). */
export function useLivePrice(symbol: string) {
  useEffect(() => {
    wireLiveStatus()
    return getSocket().on(`price:${symbol}`, (d) => {
      const p = d as LivePrice
      useLive.setState((st) => ({
        prices: { ...st.prices, [symbol]: p },
        statuses: { ...st.statuses, [symbol]: p.status },
        lastUpdate: { ...st.lastUpdate, [symbol]: Date.now() },
      }))
    })
  }, [symbol])
  return {
    price: useLive((s) => s.prices[symbol]),
    status: useLive((s) => s.statuses[symbol]),
    lastUpdate: useLive((s) => s.lastUpdate[symbol]),
  }
}

/** Live candle updates for the chart, plus a resync request after a feed reconnect. */
export function useLiveCandles(symbol: string, tf: string, apply: (bar: Candle) => void, resync: () => void) {
  useEffect(() => {
    const s = getSocket()
    const off1 = s.on(`candle:${symbol}:${tf}`, (d) => apply((d as { bar: Candle }).bar))
    const off2 = s.on(`resync:${symbol}`, () => resync())
    return () => {
      off1()
      off2()
    }
  }, [symbol, tf, apply, resync])
}

export interface StatusView {
  label: string
  tone: 'up' | 'wait' | 'down' | 'muted'
  pulse: boolean
  help: string
}

/** One honest label for the top bar: the connection to our server first, then the symbol's data feed. */
export function describeStatus(conn: string, status: SymbolStatus | undefined, source: string): StatusView {
  if (conn === 'offline') return { label: 'Offline', tone: 'down', pulse: false, help: 'No connection to the ShreeAgent server. Retrying…' }
  if (conn !== 'live') return { label: 'Reconnecting', tone: 'wait', pulse: false, help: 'Connection to the server dropped, reconnecting…' }
  switch (status) {
    case 'live':
      return { label: 'Live', tone: 'up', pulse: true, help: 'Real-time prices from OANDA' }
    case 'delayed':
      return { label: 'Delayed', tone: 'wait', pulse: false, help: `Prices from ${source || 'Yahoo'} – can be several minutes behind` }
    case 'stale':
      return { label: 'Stale', tone: 'down', pulse: false, help: 'No new prices recently while the market is open – do not trade on these numbers' }
    case 'closed':
      return { label: 'Market closed', tone: 'muted', pulse: false, help: 'The market is closed; prices are from the last session' }
    case 'error':
      return { label: 'Feed error', tone: 'down', pulse: false, help: 'The live feed reported an error (check OANDA_API_TOKEN)' }
    default:
      return { label: 'Delayed', tone: 'wait', pulse: false, help: 'Waiting for the first live price…' }
  }
}

export { useConnection }
