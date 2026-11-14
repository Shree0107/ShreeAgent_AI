import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// jsdom has no canvas: replace the chart with a stub that records what it was given.
vi.mock('./components/chart/PriceChart', async () => {
  const React = await import('react')
  return {
    PriceChart: React.forwardRef((p: { candles: unknown[]; chartType: string }, _ref) => (
      <div data-testid="price-chart">chart:{p.candles.length}:{p.chartType}</div>
    )),
  }
})

// No real WebSocket in tests.
vi.mock('./lib/ws', async () => {
  const { create } = await import('zustand')
  return { getSocket: () => ({ on: () => () => {} }), useConnection: create(() => ({ state: 'live' })) }
})

const candles = Array.from({ length: 30 }, (_, i) => ({ time: 1_700_000_000 + i * 3600, open: 1.1, high: 1.11, low: 1.09, close: 1.1, volume: 0 }))

function mockFetch() {
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url)
    const body = u.startsWith('/api/timeframes') ? ['1h', '4h', '1d', '1wk']
      : u.startsWith('/api/candles') ? { symbol: 'EUR/USD', tf: '1h', source: 'yfinance', candles, has_more: false }
      : u.startsWith('/api/quote') ? { symbol: 'EUR/USD', price: 1.09412, change_pct: 0.18, as_of: '', source: 'yfinance' }
      : u.startsWith('/api/symbols/resolve') ? { ticker: 'EUR/USD', name: 'Euro / US dollar', decimals: 5, has_volume: false, is_fx: true }
      : u.startsWith('/api/symbols/search') ? [{ ticker: 'GBP/USD', name: 'British pound / US dollar', market: 'FX' }]
      : u.startsWith('/api/watchlist') ? ['EUR/USD'] : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
}

async function renderApp() {
  const { default: App } = await import('./App')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><App /></QueryClientProvider>)
}

describe('App shell', () => {
  beforeEach(() => {
    localStorage.clear()
    mockFetch()
  })

  it('shows the top bar, 5 tabs and the chart with candles', async () => {
    await renderApp()
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Chart', 'Trade Plan', 'Fundamentals', 'Forecast', 'Performance'])
    await waitFor(() => expect(screen.getByTestId('price-chart')).toHaveTextContent('chart:30:candles'))
    expect(await screen.findByText('1.09412')).toBeInTheDocument()
    expect(screen.getByText('+0.18%', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/Delayed/)).toBeInTheDocument() // Yahoo prices are never labelled live
  })

  it('switches chart type and tabs, and disables timeframes without data', async () => {
    const user = userEvent.setup()
    await renderApp()
    await user.click(screen.getByRole('button', { name: 'Heikin Ashi' }))
    await waitFor(() => expect(screen.getByTestId('price-chart')).toHaveTextContent('heikin'))
    expect(screen.getByRole('button', { name: '15m' })).toBeDisabled()
    await user.click(screen.getByRole('tab', { name: 'Forecast' }))
    expect(await screen.findByText(/TimesFM-3 forecasts/)).toBeInTheDocument()
  })

  it('searches symbols and opens the result', async () => {
    const user = userEvent.setup()
    await renderApp()
    await user.type(screen.getByLabelText('Search symbol'), 'gbp')
    const hit = await screen.findByText('GBP/USD', {}, { timeout: 2000 })
    await user.pointer({ target: hit, keys: '[MouseLeft>]' })
    await waitFor(() => expect(screen.getByRole('button', { name: /★ GBP\/USD/ })).toBeInTheDocument())
  })
})
