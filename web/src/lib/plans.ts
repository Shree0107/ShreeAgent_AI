// Intraday trade plans (/api/plans) and the daily swing cards (/api/signals): types, fetchers and pure helpers
// (decision label, live distances, staleness, status timeline). All numbers come from the backend.
import type { OShape } from './overlay'

export type Action = 'BUY' | 'SELL' | 'WAIT'
export type PlanStateName =
  | 'pending' | 'waiting' | 'ready' | 'triggered' | 'in_trade' | 'tp1_hit' | 'tp2_hit' | 'sl_hit' | 'breakeven'
  | 'time_stop' | 'cancelled' | 'expired' | 'market_closed'

export interface Scenario {
  direction: 'long' | 'short'
  price: number
  likely_pct: number
  entry_type: 'stop' | 'limit'
  text: string
  why: string
}

export interface PlanSize {
  currency: string
  lots: number | null
  units: number
  actual_risk: number
  gain_target1: number
  gain_target2: number
  too_small: boolean
}

export interface PlanExplanation {
  headline: string
  why: string[]
  waiting_for: string[]
  entry_text?: string
  order_text?: string
  stop_text?: string
  stop_reason?: string
  targets: { label: string; price: number; text: string }[]
  rr_text?: string
  rr_money_text?: string
  breakeven_text?: string
  cancel: string[]
  time_stop_text?: string
  probability_text?: string
  time_window_text?: string
  confidence_text?: string
  news_warning?: string | null
  closest_idea?: string
  size_text?: string
  size_note?: string
  stop_money?: string
  tp1_money?: string
  tp2_money?: string
  glossary?: Record<string, string>
  disclaimer: string
}

export interface MTFRow {
  tf: string
  direction: 'up' | 'down' | 'neutral'
  score: number
  details: string[]
}

export interface PlanCard {
  symbol: string
  name?: string
  action: Action
  state: PlanStateName
  state_text?: string
  setup: string | null
  setup_name?: string | null
  direction: 'long' | 'short' | null
  entry: number | null
  entry_low: number | null
  entry_high: number | null
  entry_type: 'limit' | 'stop' | null
  stop: number | null
  target1: number | null
  target2: number | null
  generated_at: string
  expires_at: string
  flat_by?: string
  market: 'trending_up' | 'trending_down' | 'sideways'
  market_text?: string
  session_label?: string
  market_open?: boolean
  range: { low: number; high: number } | null
  scenarios: Scenario[]
  probability: { win_rate: number; n: number } | null
  size: PlanSize | null
  confidence?: string
  explanation: PlanExplanation
  details: {
    mtf?: MTFRow[]
    confirmations?: { key: string; plain: string; detail: string; tf: string }[]
    gates?: { code: string; text: string }[]
    levels?: { price: number; kind: string; label: string }[]
    spread?: { pips: number | null; live: boolean; note: string; max?: number }
    score?: number
    market?: { adx: number | null; reason: string }
    candidates?: { setup: string; direction: string; entry: number; rr1: number; gates: string[] }[]
    atr15_pips?: number | null
  }
  stale: boolean
  price: number | null
  decimals?: number
  pip_size: number | null
  is_fx?: boolean
  plan_state?: { stop_now: number | null; be_moved: boolean; fill: number | null } | null
  strength?: number
  closed?: boolean
  error?: string | null
}

export interface PlansResponse {
  cards: PlanCard[]
  generated_at: string
  refresh_job: { id: string } | null
  config: { min_rr: number; flat_by: string; no_new_entries_after: string; timezone?: string }
  account: { size: number; risk_pct: number; currency: string }
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return (await r.json()) as T
}

const qs = (p: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)])).toString()

export type Account = {
  account?: number
  risk?: number
  ccy?: string
}

export const plansApi = {
  plans: (a: Account = {}, symbols?: string) => getJson<PlansResponse>(`/api/plans?${qs({ ...a, symbols })}`),
  refresh: () => getJson<{ id: string }>('/api/plans/refresh', { method: 'POST' }),
  swing: (a: Account = {}) => getJson<{ cards: SwingCard[] }>(`/api/signals?${qs(a)}`),
}

// ---------------------------------------------------------------- decision label
export interface Decision {
  label: 'BUY' | 'SELL' | 'WAIT' | 'GET READY'
  tone: 'up' | 'down' | 'wait' | 'ready'
}

export function decisionOf(c: Pick<PlanCard, 'action' | 'state'>): Decision {
  if ((c.action === 'BUY' || c.action === 'SELL') && c.state === 'ready') return { label: 'GET READY', tone: 'ready' }
  if (c.action === 'BUY') return { label: 'BUY', tone: 'up' }
  if (c.action === 'SELL') return { label: 'SELL', tone: 'down' }
  return { label: 'WAIT', tone: 'wait' }
}

export type Filter = 'all' | 'buy' | 'sell' | 'ready' | 'wait'
export function matchesFilter(c: PlanCard, f: Filter): boolean {
  const d = decisionOf(c).label
  if (f === 'all') return true
  if (f === 'ready') return d === 'GET READY'
  if (f === 'buy') return c.action === 'BUY'
  if (f === 'sell') return c.action === 'SELL'
  return c.action === 'WAIT'
}

export function sortCards(cards: PlanCard[]): PlanCard[] {
  return [...cards].sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0))
}

// ---------------------------------------------------------------- distances
/** "6 pips" (forex) or "0.4%" (stocks). */
export function fmtDist(a: number, b: number, pip: number | null): string {
  if (pip) return `${Math.round(Math.abs(a - b) / pip)} pips`
  return `${((Math.abs(a - b) / a) * 100).toFixed(1)}%`
}

export interface LiveDistances {
  entry: string | null
  stop: string | null
  target1: string | null
  sentence: string | null
}

const IN_TRADE: PlanStateName[] = ['triggered', 'in_trade', 'tp1_hit']

/** Plain distances from the live price to the entry, the stop and target 1. */
export function liveDistances(c: PlanCard, price: number | null | undefined): LiveDistances {
  const none = { entry: null, stop: null, target1: null, sentence: null }
  if (price === null || price === undefined || c.entry === null || c.stop === null || c.target1 === null) return none
  const p = c.pip_size
  const stop = c.plan_state?.stop_now ?? c.stop
  const out: LiveDistances = { entry: fmtDist(price, c.entry, p), stop: fmtDist(price, stop, p), target1: fmtDist(price, c.target1, p), sentence: null }
  if (IN_TRADE.includes(c.state)) {
    out.sentence = `Price is ${out.target1} from target 1 and ${out.stop} from the stop loss`
  } else if (c.action !== 'WAIT') {
    const at = Math.abs(price - c.entry) < (p ?? price * 0.0001) / 2
    out.sentence = at ? 'Price is at the entry now' : `Price is ${out.entry} away from entry`
  }
  return out
}

// ---------------------------------------------------------------- staleness
const CANDLE_S = 15 * 60

export interface Staleness {
  stale: boolean
  label: string | null
}

/** Grey a card when it is older than one 15M candle, or when the feed is stale/closed (never show old data as live). */
export function staleness(c: Pick<PlanCard, 'generated_at' | 'stale' | 'state'>, nowMs: number, feed?: string): Staleness {
  if (c.state === 'market_closed' || feed === 'closed') return { stale: true, label: 'Market closed – prices are from the last session' }
  if (feed === 'stale' || feed === 'error') return { stale: true, label: 'Price feed not updating – do not trade on these numbers' }
  const age = (nowMs - Date.parse(c.generated_at)) / 1000
  if (c.state === 'pending') return { stale: true, label: 'Analysing…' }
  if (c.stale || age > CANDLE_S + 60) return { stale: true, label: `Out of date (${Math.round(age / 60)} min old) – updating…` }
  return { stale: false, label: null }
}

// ---------------------------------------------------------------- status timeline
export const TIMELINE: { id: string; label: string }[] = [
  { id: 'waiting', label: 'Waiting' },
  { id: 'ready', label: 'Ready' },
  { id: 'triggered', label: 'Entry triggered' },
  { id: 'in_trade', label: 'In trade' },
  { id: 'result', label: 'Result' },
]

const RESULT: Partial<Record<PlanStateName, string>> = {
  tp1_hit: 'Target 1 hit', tp2_hit: 'Target 2 hit', sl_hit: 'Stop loss hit', breakeven: 'Break-even',
  time_stop: 'Time stop', cancelled: 'Cancelled', expired: 'Expired',
}

/** Index of the active step (0..4) and the result label when there is one. */
export function timelineStep(state: PlanStateName, closed = false): { step: number; result: string | null } {
  if (state === 'tp1_hit' && !closed) return { step: 3, result: 'Target 1 hit – running to target 2' }
  if (RESULT[state]) return { step: 4, result: RESULT[state] ?? null }
  const i = TIMELINE.findIndex((t) => t.id === state)
  return { step: i < 0 ? 0 : i, result: null }
}

// ---------------------------------------------------------------- mini chart shapes
export function planShapes(c: PlanCard): OShape[] {
  const out: OShape[] = []
  if (c.entry !== null && c.entry_low !== null && c.entry_high !== null && c.entry_high - c.entry_low > 0) {
    const t0 = Math.floor(Date.parse(c.generated_at) / 1000) - 4 * 3600
    out.push({ kind: 'box', t1: t0, t2: 'right', p1: c.entry_low, p2: c.entry_high, fill: 'rgba(59,130,246,0.15)', label: 'Entry zone' })
  }
  if (c.entry !== null) out.push({ kind: 'hline', price: c.entry, color: '#3b82f6', label: 'Entry', width: 2 })
  const stop = c.plan_state?.stop_now ?? c.stop
  if (stop !== null) out.push({ kind: 'hline', price: stop, color: '#ef4444', label: 'Stop loss', dash: true })
  if (c.target1 !== null) out.push({ kind: 'hline', price: c.target1, color: '#22c55e', label: 'Target 1', dash: true })
  if (c.target2 !== null) out.push({ kind: 'hline', price: c.target2, color: '#22c55e', label: 'Target 2', dash: true })
  if (c.action === 'WAIT' && c.range) {
    out.push({ kind: 'hline', price: c.range.high, color: '#f59e0b', label: 'Top of range', dash: true })
    out.push({ kind: 'hline', price: c.range.low, color: '#f59e0b', label: 'Bottom of range', dash: true })
  }
  return out
}

// ---------------------------------------------------------------- swing (daily) cards, existing /api/signals
export interface SwingCard {
  symbol: string
  name?: string
  action: 'BUY' | 'SELL' | 'WAIT' | 'PENDING' | 'ERROR'
  confidence?: string
  price_text?: string
  generated_at?: string
  stale?: boolean
  message?: string
  error?: string
  levels?: { entry_low: number; entry_high: number; stop: number; target1: number; target2: number } | null
  explanation?: {
    reasons: string[]
    waiting_for: string[]
    entry_text: string
    stop_text: string
    stop_why: string
    targets: { label: string; price_text: string; distance: string; money: string | null; why: string }[]
    cancel: string[]
    rr_text: string
    size_text: string
    confidence_text: string
    event_warning: string | null
    disclaimer: string
  }
}
