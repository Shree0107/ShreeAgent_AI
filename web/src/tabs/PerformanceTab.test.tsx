import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { minutesText, sortRows, type PerfRow } from '../lib/perf'

function row(over: Partial<PerfRow>): PerfRow {
  return {
    setup: 'squeeze_breakout', setup_name: 'Breakout after a quiet period', symbol: 'EUR/USD', session: 'all',
    session_name: 'All sessions', trades: 100, wins: 58, win_rate: 0.58, avg_win_pips: 12, avg_loss_pips: 9,
    profit_factor: 1.4, max_drawdown_pips: 45, expectancy_pips: 2.1, total_pips: 210, breakeven_win_rate: 0.43,
    best_hours: [], worst_hours: [], median_minutes_to_tp1: 95, p25_minutes_to_tp1: 40, p75_minutes_to_tp1: 180,
    ...over,
  }
}

const summaryFull = {
  has_backtest: true, empty_text: null,
  runs: [{ symbol: 'EUR/USD', generated_at: '2026-11-14T10:00:00+00:00', method: 'single_split',
           method_text: 'Only a short history was available, so the settings were chosen on the first 60% of it.',
           out_of_sample: true, period: { start: '2026-10-20', end: '2026-11-13' }, period_text: '24 days',
           windows: [], notes: ['Only 58 days of 5-minute history were available (Yahoo keeps about 60 days).'], overall: null }],
  rows: [row({}), row({ session: 'london', session_name: 'London', trades: 40, wins: 25, win_rate: 0.625 }),
         row({ setup: 'trend_pullback', setup_name: 'Pullback in the trend', trades: 12, wins: 4, win_rate: 0.33, profit_factor: 0.7 })],
  lines: ['Breakout after a quiet period reached target 1 in 58 of 100 trades on EUR/USD (last 24 days, one out-of-sample test).'],
  disabled: [{ symbol: 'EUR/USD', setup: 'trend_pullback', setup_name: 'Pullback in the trend',
               reason: 'Only 12 test trades – at least 50 are needed before the results can be trusted.' }],
}
const summaryEmpty = { has_backtest: false, runs: [], rows: [], lines: [], disabled: [],
  empty_text: 'No backtest yet – click Run backtest. With Yahoo data only about 60 days of 5-minute history is available, so the results are a rough guide.' }
const liveBody = {
  overall: { live: { trades: 3, wins: 2, win_rate: 0.67, profit_factor: 4, avg_pips: 10, total_pips: 30 },
             backtest: { win_rate: 0.55, trades: 112, avg_pips: 1.8 }, band: { low: 0.0, high: 1.0, level: 0.9 },
             status: 'inside', sentence: 'Live results are inside the range the backtest expected (67% reached target 1; expected 0–100% for 3 trades).' },
  rows: [],
}
const equityBody = { backtest: { 'EUR/USD': [{ t: '2026-11-01T10:00:00Z', pips: 5 }, { t: '2026-11-02T10:00:00Z', pips: -3 }] }, live: [] }

let runStatus: unknown = { symbol: 'EUR/USD', job: null, progress: null }
let posted = 0

function mockFetch(summary: unknown) {
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url)
    if (u.startsWith('/api/performance/run') && init?.method === 'POST') {
      posted += 1
      runStatus = { symbol: 'EUR/USD', job: { id: 'j1', key: 'performance:EUR/USD', kind: 'performance', status: 'running', error: null },
                    progress: { stage: 'cards', done: 50, total: 100, message: 'Replaying the engine: 50 of 100 15-minute candles' } }
      return new Response(JSON.stringify({ id: 'j1', status: 'running' }), { status: 200 })
    }
    const body = u.startsWith('/api/performance/summary') ? summary
      : u.startsWith('/api/performance/live-vs-backtest') ? liveBody
      : u.startsWith('/api/performance/equity') ? equityBody
      : u.startsWith('/api/performance/run') ? runStatus
      : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
}

async function renderTab() {
  const { default: PerformanceTab } = await import('./PerformanceTab')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><PerformanceTab /></QueryClientProvider>)
}

describe('PerformanceTab', () => {
  beforeEach(() => {
    localStorage.clear()
    runStatus = { symbol: 'EUR/USD', job: null, progress: null }
    posted = 0
  })

  it('shows plain lines, disabled setups, the table, live comparison and the equity curve', async () => {
    mockFetch(summaryFull)
    await renderTab()
    expect(await screen.findByText(/reached target 1 in 58 of 100 trades on EUR\/USD/)).toBeInTheDocument()
    expect(screen.getByText(/Yahoo keeps about 60 days/)).toBeInTheDocument()
    const dis = screen.getByTestId('disabled')
    expect(within(dis).getByText(/at least 50 are needed/)).toBeInTheDocument()
    const rows = within(screen.getByTestId('table')).getAllByTestId('perf-row')
    expect(rows).toHaveLength(2) // the "all sessions" rows only
    expect(within(rows[0]).getByText('100')).toBeInTheDocument()
    expect(within(rows[0]).getByText('95 min (40 min–3.0 h)')).toBeInTheDocument()
    expect(await screen.findByText(/Live results are inside the range/)).toBeInTheDocument()
    expect(screen.getByText('As expected')).toBeInTheDocument()
    expect(await screen.findByText(/Backtest \(test period\): -3.0 pips after 2 trades/)).toBeInTheDocument()
  })

  it('sorts the table and splits it by session', async () => {
    const user = userEvent.setup()
    mockFetch(summaryFull)
    await renderTab()
    await screen.findByTestId('table')
    await user.click(screen.getByRole('button', { name: /Profit factor/ }))
    let rows = screen.getAllByTestId('perf-row')
    expect(within(rows[0]).getByText('Breakout after a quiet period')).toBeInTheDocument()   // 1.40 first (descending)
    await user.click(screen.getByRole('button', { name: /Profit factor/ }))
    rows = screen.getAllByTestId('perf-row')
    expect(within(rows[0]).getByText('Pullback in the trend')).toBeInTheDocument()
    await user.click(screen.getByLabelText(/Split by session/))
    rows = screen.getAllByTestId('perf-row')
    expect(rows).toHaveLength(1)
    expect(within(rows[0]).getByText('London')).toBeInTheDocument()
  })

  it('shows the empty state and starts a backtest with progress', async () => {
    const user = userEvent.setup()
    mockFetch(summaryEmpty)
    await renderTab()
    expect(await screen.findByText(/No backtest yet – click Run backtest/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Run backtest (EUR/USD)' }))
    expect(posted).toBe(1)
    expect(await screen.findByText(/Replaying the engine: 50 of 100/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Backtest running…' })).toBeDisabled()
  })

  it('shows an error when the results cannot be loaded', async () => {
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({ detail: 'boom' }), { status: 500 })) as typeof fetch
    await renderTab()
    expect(await screen.findByText(/Couldn't load the backtest results: boom/)).toBeInTheDocument()
  })
})

describe('perf helpers', () => {
  it('formats time to target 1 and sorts with empty values last', () => {
    expect(minutesText(row({}))).toBe('95 min (40 min–3.0 h)')
    expect(minutesText(row({ median_minutes_to_tp1: null }))).toBe('–')
    const r = sortRows([row({ profit_factor: null }), row({ profit_factor: 2 }), row({ profit_factor: 1 })], 'profit_factor', 1)
    expect(r.map((x) => x.profit_factor)).toEqual([1, 2, null])
  })
})
