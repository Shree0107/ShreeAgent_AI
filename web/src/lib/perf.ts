// Performance tab (phase 7) client for /api/performance/*: backtest results and live tracking.
import { ApiError, type Job } from './api'

export interface HourStat { hour: number; trades: number; avg_pips: number }

export interface PerfRow {
  setup: string
  setup_name: string
  symbol: string
  session: string
  session_name: string
  trades: number
  wins: number
  win_rate: number | null
  avg_win_pips: number | null
  avg_loss_pips: number | null
  profit_factor: number | null
  max_drawdown_pips: number
  expectancy_pips: number | null
  total_pips: number
  breakeven_win_rate: number | null
  best_hours: HourStat[]
  worst_hours: HourStat[]
  median_minutes_to_tp1: number | null
  p25_minutes_to_tp1: number | null
  p75_minutes_to_tp1: number | null
}

export interface RunInfo {
  symbol: string
  generated_at: string
  method: 'walk_forward' | 'single_split' | 'in_sample'
  method_text: string
  out_of_sample: boolean
  period: { start: string; end: string }
  period_text: string
  windows: { test_start: string; test_end: string; chosen: string; test_trades: number }[]
  notes: string[]
  overall: PerfRow | null
}

export interface Disabled { symbol: string; setup: string; setup_name: string; reason: string }

export interface Summary {
  has_backtest: boolean
  empty_text: string | null
  runs: RunInfo[]
  rows: PerfRow[]
  lines: string[]
  disabled: Disabled[]
}

export interface EquityPoint { t: string; pips: number }
export interface Equity { backtest: Record<string, EquityPoint[]>; live: EquityPoint[] }

export interface LiveStats {
  trades: number
  wins: number
  win_rate: number | null
  profit_factor: number | null
  avg_pips: number | null
  total_pips: number
}

export interface Comparison {
  live: LiveStats
  backtest: { win_rate: number | null; trades: number; avg_pips: number | null }
  band: { low: number; high: number; level: number } | null
  status: 'no_backtest' | 'no_live' | 'inside' | 'below' | 'above'
  sentence: string
}

export interface LiveVsBacktest {
  overall: Comparison
  rows: (Comparison & { symbol: string; setup: string; setup_name: string })[]
}

export interface Progress { stage: string; done: number; total: number; message: string }
export interface RunStatus { symbol: string; job: (Job & { result?: { lines?: string[] } }) | null; progress: Progress | null }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
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

const sym = (s?: string) => (s ? `?symbol=${encodeURIComponent(s)}` : '')

export const perfApi = {
  summary: () => req<Summary>('/api/performance/summary'),
  equity: (symbol: string) => req<Equity>(`/api/performance/equity${sym(symbol)}`),
  liveVsBacktest: () => req<LiveVsBacktest>('/api/performance/live-vs-backtest'),
  run: (symbol: string) => req<Job>(`/api/performance/run${sym(symbol)}`, { method: 'POST' }),
  status: (symbol: string) => req<RunStatus>(`/api/performance/run${sym(symbol)}`),
}

export const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(d)}%`)
export const num = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '–' : v.toFixed(d))
export const signed = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(d)}`

export function minutesText(r: Pick<PerfRow, 'median_minutes_to_tp1' | 'p25_minutes_to_tp1' | 'p75_minutes_to_tp1'>): string {
  if (r.median_minutes_to_tp1 === null) return '–'
  const m = (x: number | null) => (x === null ? '?' : x >= 120 ? `${(x / 60).toFixed(1)} h` : `${Math.round(x)} min`)
  return `${m(r.median_minutes_to_tp1)} (${m(r.p25_minutes_to_tp1)}–${m(r.p75_minutes_to_tp1)})`
}

export type SortKey = 'setup_name' | 'symbol' | 'session_name' | 'trades' | 'win_rate' | 'profit_factor' |
  'expectancy_pips' | 'max_drawdown_pips' | 'median_minutes_to_tp1'

export function sortRows(rows: PerfRow[], key: SortKey, dir: 1 | -1): PerfRow[] {
  return [...rows].sort((a, b) => {
    const x = a[key], y = b[key]
    if (x === null || x === undefined) return 1
    if (y === null || y === undefined) return -1
    if (typeof x === 'string' || typeof y === 'string') return String(x).localeCompare(String(y)) * dir
    return ((x as number) - (y as number)) * dir
  })
}
