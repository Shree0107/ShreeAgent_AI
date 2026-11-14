// Typed client for the FastAPI backend (/api/*).

export interface Candle {
  time: number // unix seconds, UTC
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface CandlesResponse {
  symbol: string
  tf: string
  source: string
  candles: Candle[]
  has_more: boolean
}

export interface SymbolInfo {
  ticker: string
  name: string
  asset_class: string
  market: string
  is_fx: boolean
  has_volume: boolean
  pip_size: number | null
  decimals: number
  investing_url: string
  exchange?: string
}

export interface Quote {
  symbol: string
  price: number
  change_pct: number
  as_of: string
  source: string
}

export interface Job {
  id: string
  key: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'error'
  error: string | null
  result?: unknown
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
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

const qs = (p: Record<string, string | number | boolean | undefined | null>) =>
  new URLSearchParams(
    Object.entries(p)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()

export const api = {
  timeframes: () => request<string[]>('/api/timeframes'),
  candles: (symbol: string, tf: string, limit = 500, before?: number) =>
    request<CandlesResponse>(`/api/candles?${qs({ symbol, tf, limit, before })}`),
  quote: (symbol: string) => request<Quote>(`/api/quote?${qs({ symbol })}`),
  resolve: (symbol: string) => request<SymbolInfo>(`/api/symbols/resolve?${qs({ symbol })}`),
  search: (q: string) => request<SymbolInfo[]>(`/api/symbols/search?${qs({ q })}`),
  watchlist: () => request<string[]>('/api/watchlist'),
  addToWatchlist: (symbol: string) =>
    request<string[]>('/api/watchlist', { method: 'POST', body: JSON.stringify({ symbol }) }),
  removeFromWatchlist: (symbol: string) =>
    request<string[]>(`/api/watchlist?${qs({ symbol })}`, { method: 'DELETE' }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  settings: () => request<Record<string, unknown>>('/api/settings'),
}
