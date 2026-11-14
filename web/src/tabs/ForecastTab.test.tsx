import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { isOutdated, secondsToUpdate, type LiveForecast } from '../lib/forecast'

// jsdom has no canvas: replace the chart with a stub that shows what it was given.
vi.mock('../components/forecast/ForecastChart', () => ({
  ForecastChart: (p: { candles: unknown[]; forecast: { median: number[] } | null; outdated: boolean }) => (
    <div data-testid="fc-stub">chart:{p.candles.length}:{p.forecast?.median.length ?? 0}:{p.outdated ? 'old' : 'fresh'}</div>
  ),
}))
vi.mock('../lib/ws', async () => {
  const { create } = await import('zustand')
  return { getSocket: () => ({ on: () => () => {} }), useConnection: create(() => ({ state: 'live' })) }
})

const H = 24
const nowIso = new Date().toISOString()
const future = new Date(Date.now() + 30 * 60_000).toISOString()

function liveBody(over: Partial<LiveForecast> = {}): LiveForecast {
  return {
    symbol: 'EUR/USD', tf: '1h', horizon: H, horizon_text: '24 hours', now: nowIso, stale: false, age_s: 120,
    next_update_at: future, refresh_job: null, variates_text: 'Only this market\'s own prices are used.',
    forecast: {
      made_at: nowIso, last_bar_time: nowIso, last_close: 1.0930, model: 'timesfm-3', variates: ['close'],
      dates: Array.from({ length: H }, (_, i) => new Date(Date.now() + (i + 1) * 3600_000).toISOString()),
      median: Array(H).fill(1.0938), q10: Array(H).fill(1.089), q25: Array(H).fill(1.091), q75: Array(H).fill(1.096),
      q90: Array(H).fill(1.0985), prob_up: 0.58, expected_change_pct: 0.07, baselines: {}, direction: 'up',
      direction_words: 'slightly upward',
      summary: 'The model expects EUR/USD to be between 1.0910 and 1.0960 in the next 24 hours, slightly upward.',
    },
    check: {
      status: 'worse', run_at: nowIso, units: 'pips', n_windows: 20, coverage_50: 48, coverage_80: 77,
      text: 'On EUR/USD 1-hour forecasts the model has not done better than simply assuming "price stays the same" in 20 past tests. Treat it as a rough guide.',
      table: [
        { name: 'model', label: 'Model (timesfm-3)', error: 14.2, direction_pct: 51 },
        { name: 'naive', label: 'Price stays the same', error: 13.9, direction_pct: null },
        { name: 'drift', label: 'Recent trend continues', error: 15.1, direction_pct: 49 },
        { name: 'moving_average', label: 'Back to the 20-candle average', error: 16, direction_pct: 47 },
      ],
    },
    ...over,
  }
}

const accBody = {
  symbol: 'EUR/USD', tf: '1h', horizon: H, units: 'pips',
  stats: { n: 3, units: 'pips', direction_n: 3, direction_hits: 2, direction_pct: 66.7, mae: 10, naive_mae: 12, in50_pct: 50, in80_pct: 80 },
  text: 'Of the last 3 finished forecasts, the direction was right 2 of 3 times.',
  recent: [
    { made_at: nowIso, last_bar_time: '2026-11-13T10:00:00+00:00', last_close: 1.09, predicted_end: 1.0950, actual_end: 1.0921,
      predicted_dir: 'up', actual_dir: 'up', dir_correct: true, error: 9.5, end_in50: true, end_in80: true },
    { made_at: nowIso, last_bar_time: '2026-11-13T09:00:00+00:00', last_close: 1.09, predicted_end: 1.0950, actual_end: 1.0870,
      predicted_dir: 'up', actual_dir: 'down', dir_correct: false, error: 20.1, end_in50: false, end_in80: true },
  ],
}

function mockFetch(live: LiveForecast, agree: unknown) {
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url)
    const body = u.startsWith('/api/forecast/live') ? live
      : u.startsWith('/api/forecast/accuracy') ? accBody
      : u.startsWith('/api/forecast/agreement') ? agree
      : u.startsWith('/api/timeframes') ? ['15m', '1h', '4h', '1d']
      : u.startsWith('/api/candles') ? { symbol: 'EUR/USD', tf: '1h', source: 'x', has_more: false,
                                         candles: Array.from({ length: 10 }, (_, i) => ({ time: i, open: 1, high: 1, low: 1, close: 1, volume: 0 })) }
      : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
}

async function renderTab() {
  const { default: ForecastTab } = await import('./ForecastTab')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ForecastTab /></QueryClientProvider>)
}

describe('ForecastTab', () => {
  beforeEach(() => localStorage.clear())

  it('shows the summary, verdict, accuracy and agreement in plain words', async () => {
    mockFetch(liveBody(), { status: 'agree', text: 'The forecast agrees with the BUY plan.', forecast_direction: 'up',
                            plan: { source: 'intraday', action: 'BUY' } })
    await renderTab()
    expect(await screen.findByText(/between 1.0910 and 1.0960 in the next 24 hours, slightly upward/)).toBeInTheDocument()
    expect(await screen.findByText('The forecast agrees with the BUY plan.')).toBeInTheDocument()
    expect(screen.getByText(/intraday trade plan/)).toBeInTheDocument()
    const verdict = screen.getByTestId('verdict')
    expect(within(verdict).getByText('Worse than simple guesses')).toBeInTheDocument()
    expect(within(verdict).getByText(/has not done better than simply assuming/)).toBeInTheDocument()
    expect(within(verdict).queryByRole('table')).toBeNull() // numbers only behind "Show details"
    const acc = await screen.findByTestId('accuracy')
    expect(await within(acc).findByText(/right 2 of 3 times/)).toBeInTheDocument()
    expect(within(acc).getByText('right')).toBeInTheDocument()
    expect(within(acc).getByText('wrong')).toBeInTheDocument()
    expect(await screen.findByText(/chart:10:24:fresh/)).toBeInTheDocument()
    expect(screen.getByText(/Next update in 2\d:\d\d/)).toBeInTheDocument()
  })

  it('reveals the model-vs-baselines table behind Show details', async () => {
    const user = userEvent.setup()
    mockFetch(liveBody(), { status: 'none', text: 'No trade plan is available to compare with.', forecast_direction: 'up', plan: null })
    await renderTab()
    await screen.findByTestId('summary')
    await user.click(screen.getByRole('button', { name: 'Show details' }))
    const table = within(screen.getByTestId('verdict')).getByRole('table')
    expect(within(table).getByText('Price stays the same')).toBeInTheDocument()
    expect(within(table).getByText('13.9')).toBeInTheDocument()
    expect(screen.getByTestId('tech-details')).toHaveTextContent('timesfm-3')
  })

  it('greys out an old forecast and warns about disagreement', async () => {
    const past = new Date(Date.now() - 3600_000).toISOString()
    mockFetch(liveBody({ stale: true, next_update_at: past }),
              { status: 'disagree', text: 'The forecast points down while the plan says BUY – be careful.',
                forecast_direction: 'down', plan: { source: 'daily', action: 'BUY' } })
    await renderTab()
    expect(await screen.findByText(/Out of date/)).toBeInTheDocument()
    expect(await screen.findByText(/be careful/)).toBeInTheDocument()
    expect(screen.getByText(/daily signal/)).toBeInTheDocument()
    expect(await screen.findByText(/:old/)).toBeInTheDocument()
  })

  it('shows a waiting state before the first forecast', async () => {
    mockFetch(liveBody({ forecast: null, check: null, next_update_at: null,
                         refresh_job: { id: 'j', key: 'fclive:EUR/USD:1h:24', kind: 'forecast_live', status: 'running', error: null } }),
              { status: 'none', text: 'No forecast yet to compare with the trade plan.', forecast_direction: null, plan: null })
    await renderTab()
    expect(await screen.findByText(/Making the first forecast/)).toBeInTheDocument()
    expect(screen.getByText('Updating now…')).toBeInTheDocument()
  })
})

describe('forecast helpers', () => {
  it('knows when a forecast is out of date', () => {
    const d = liveBody({ next_update_at: '2026-11-14T12:00:00Z' })
    expect(isOutdated(d, new Date('2026-11-14T11:59:00Z'))).toBe(false)
    expect(isOutdated(d, new Date('2026-11-14T12:00:00Z'))).toBe(true)
    expect(isOutdated({ ...d, stale: true }, new Date('2026-11-14T11:00:00Z'))).toBe(true)
    expect(secondsToUpdate(d, new Date('2026-11-14T11:59:00Z'))).toBe(60)
    expect(secondsToUpdate(d, new Date('2026-11-14T12:01:00Z'))).toBeNull()
  })
})
