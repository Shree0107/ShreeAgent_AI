// Fundamentals tab (phase 8) client for /api/fund/*.
import { ApiError } from './api'

export type Impact = 'high' | 'medium' | 'low' | 'holiday'

export interface CalEvent {
  time: string
  currency: string
  title: string
  plain_title: string
  impact: Impact
  forecast: string
  previous: string
  actual: string
  actual_source: string
  source: string
  time_exact: boolean
  major: boolean
  past: boolean
  type: string
  surprise: 'higher' | 'lower' | 'inline' | null
  affects_symbol: boolean
  meaning: string
}

export interface CalendarResponse {
  range: 'today' | 'week'
  range_start: string
  range_end: string
  tz: string
  now: string
  events: CalEvent[]
  next_major: (CalEvent & { meaning?: string }) | null
  focus_currencies: string[]
  source: string
  feed_ok: boolean
  notes: string[]
}

export interface Expectation {
  lean: 'cut' | 'hold' | 'hike' | 'unknown'
  label: string
  score: number
  reasons: string[]
  inputs: number
}

export interface Bank {
  currency: string
  currency_name?: string
  bank: string
  short?: string
  policy_rate?: number | null
  rate_as_of?: string | null
  rate_change_6m?: number | null
  inflation_yoy?: number | null
  inflation_target?: number | null
  yield_2y?: number | null
  next_meeting?: { date: string; time: string | null; title: string; source: string } | null
  next_meeting_text?: string
  expectation?: Expectation
  error?: string
}

export interface BanksResponse {
  banks: Bank[]
  tooltip: string
  notes: string[]
  source: string
}

export interface StrengthRow {
  currency: string
  name: string
  strength: number | null
  n_pairs: number
  rank: number | null
}

export interface StrengthResponse {
  tf: string
  currencies: StrengthRow[]
  pairs: Record<string, number | null>
  missing_pairs: string[]
  as_of: string | null
  sources: string[]
  live: boolean
  notes: string[]
}

export interface Headline {
  title: string
  source: string
  date: string
  url: string
  sentiment: number
  label: 'positive' | 'negative' | 'neutral'
}

export interface NewsResponse {
  symbol: string
  label: string
  score: number
  n_articles: number
  method: string
  headlines: Headline[]
}

export interface NewsSummaryResponse {
  symbol: string
  enabled: boolean
  note: string
  items: { title: string; summary: string | null }[]
}

export interface BiasResponse {
  symbol: string
  kind: 'fx' | 'stock'
  bias: 'bullish' | 'bearish' | 'neutral' | 'unknown'
  score: number | null
  headline: string
  why: string[]
  horizon: string
  source: string
  estimate: boolean
}

export interface Fact {
  key: string
  label: string
  value: string
  text: string
  tone: 'good' | 'bad' | 'neutral'
  tip: string
}

export interface StockResponse {
  symbol: string
  name: string | null
  sector: string | null
  price: number | null
  currency: string | null
  facts: Fact[]
  earnings: { date: string; days_away: number; text: string } | null
  analysts: { recommendation: string | null; target: number | null; upside_pct: number | null; text: string } | null
  source: string
}

async function get<T>(path: string, params: Record<string, string | undefined>): Promise<T> {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString()
  const r = await fetch(`/api/fund/${path}${q ? `?${q}` : ''}`)
  if (!r.ok) {
    let msg = r.statusText
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j)
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, msg)
  }
  return (await r.json()) as T
}

export const fundApi = {
  calendar: (p: { symbol?: string; currencies?: string; impact?: string; range: string; tz?: string }) =>
    get<CalendarResponse>('calendar', p),
  centralBanks: () => get<BanksResponse>('central-banks', {}),
  strength: (tf: string) => get<StrengthResponse>('strength', { tf }),
  news: (symbol: string) => get<NewsResponse>('news', { symbol }),
  newsSummary: (symbol: string) => get<NewsSummaryResponse>('news-summary', { symbol }),
  bias: (symbol: string) => get<BiasResponse>('bias', { symbol }),
  stock: (symbol: string) => get<StockResponse>('stock', { symbol }),
}

export function userTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** Short zone label for the user's local time, e.g. "CET" or "GMT+1". */
export function tzLabel(d = new Date()): string {
  try {
    return new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(d).find((p) => p.type === 'timeZoneName')?.value ?? ''
  } catch {
    return ''
  }
}

export function fmtLocalTime(iso: string, withDay = false): string {
  const d = new Date(iso)
  const t = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
  return withDay ? `${d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} ${t}` : t
}
