// Forecast tab API (phase 9): types, requests and small pure helpers.
import type { Job } from './api'

export interface ForecastData {
  made_at: string
  last_bar_time: string
  last_close: number
  model: string
  variates: string[]
  dates: string[]
  median: number[]
  q10: number[]
  q25: number[]
  q75: number[]
  q90: number[]
  prob_up: number
  expected_change_pct: number
  baselines: Record<string, number[]>
  direction: 'up' | 'down' | 'flat'
  direction_words: string
  summary: string
}

export interface CheckRow {
  name: string
  label: string
  error: number | null
  direction_pct: number | null
}

export interface ForecastCheck {
  status: 'better' | 'same' | 'worse' | 'unknown'
  text: string
  table: CheckRow[]
  units?: string
  n_windows?: number
  run_at: string | null
  coverage_50?: number | null
  coverage_80?: number | null
  skill_vs_naive?: number | null
  multivariate?: {
    tested: boolean
    used: boolean
    variates_tested: string[] | null
    error_own_prices: number | null
    error_with_extras: number | null
  }
}

export interface LiveForecast {
  symbol: string
  tf: string
  horizon: number
  horizon_text: string
  now: string
  forecast: ForecastData | null
  stale: boolean
  age_s: number | null
  next_update_at: string | null
  refresh_job: Job | null
  variates_text?: string
  check: ForecastCheck | null
  last_error?: string
}

export interface AccuracyRow {
  made_at: string
  last_bar_time: string
  last_close: number
  predicted_end: number
  actual_end: number
  predicted_dir: 'up' | 'down' | 'flat'
  actual_dir: 'up' | 'down' | 'flat'
  dir_correct: boolean | null
  error: number | null
  end_in50: boolean
  end_in80: boolean
}

export interface AccuracyStats {
  n: number
  units: string
  direction_n?: number
  direction_hits?: number
  direction_pct?: number | null
  mae?: number
  naive_mae?: number
  in50_pct?: number
  in80_pct?: number
}

export interface Accuracy {
  symbol: string
  tf: string
  horizon: number
  units: string
  stats: AccuracyStats
  text: string
  recent: AccuracyRow[]
}

export interface Agreement {
  status: 'agree' | 'disagree' | 'neutral' | 'none'
  text: string
  forecast_direction: string | null
  plan: { source: 'intraday' | 'daily'; action: string; direction?: string | null; generated_at?: string } | null
}

export const FORECAST_TFS = [
  { id: '15m', label: '15M', seconds: 900 },
  { id: '1h', label: '1H', seconds: 3600 },
  { id: '4h', label: '4H', seconds: 14400 },
  { id: '1d', label: 'D', seconds: 86400 },
] as const

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    let msg = r.statusText
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : msg
    } catch {
      /* not JSON */
    }
    throw new Error(msg || `HTTP ${r.status}`)
  }
  return (await r.json()) as T
}

const q = (symbol: string, tf: string) => `symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}`

export const forecastApi = {
  live: (symbol: string, tf: string) => get<LiveForecast>(`/api/forecast/live?${q(symbol, tf)}`),
  refresh: (symbol: string, tf: string) => get<Job>(`/api/forecast/live/refresh?${q(symbol, tf)}`, { method: 'POST' }),
  accuracy: (symbol: string, tf: string, limit = 12) => get<Accuracy>(`/api/forecast/accuracy?${q(symbol, tf)}&limit=${limit}`),
  agreement: (symbol: string, tf: string) => get<Agreement>(`/api/forecast/agreement?${q(symbol, tf)}`),
}

export const toUnix = (iso: string) => Math.floor(Date.parse(iso) / 1000)

/** Out of date once a newer candle has closed than the one the forecast used (server says so too). */
export function isOutdated(d: LiveForecast, now: Date): boolean {
  if (!d.forecast || !d.next_update_at) return true
  return d.stale || now.getTime() >= Date.parse(d.next_update_at)
}

/** Seconds until the next scheduled update, or null when it is already due. */
export function secondsToUpdate(d: LiveForecast, now: Date): number | null {
  if (!d.next_update_at) return null
  const s = (Date.parse(d.next_update_at) - now.getTime()) / 1000
  return s > 0 ? s : null
}

export function fmtAge(seconds: number): string {
  if (seconds < 60) return 'just now'
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}

export function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
