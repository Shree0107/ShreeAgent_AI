import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { buyCard, waitCard } from '../../lib/__fixtures__/plans'
import type { PlanCard as Card } from '../../lib/plans'

// jsdom has no canvas: the mini chart is a stub that shows how many shapes it would draw.
vi.mock('../chart/PriceChart', () => ({
  PriceChart: (p: { candles: unknown[]; overlay?: unknown[] }) => <div data-testid="mini-chart">{p.candles.length}:{p.overlay?.length}</div>,
}))

const { PlanCard } = await import('./PlanCard')

const NOW = Date.parse('2026-11-11T12:05:00Z')
const JARGON = ['RSI', 'MACD', 'ATR', 'EMA', 'SMA', 'Fibonacci', 'BOS', 'CHoCH', 'ADX', 'Bollinger', 'Stochastic', 'VWAP', 'pivot']

beforeEach(() => {
  globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({
    symbol: 'EUR/USD', tf: '15m', source: 'yfinance', has_more: false,
    candles: Array.from({ length: 20 }, (_, i) => ({ time: 1_700_000_000 + i * 900, open: 1.09, high: 1.1, low: 1.08, close: 1.09, volume: 0 })),
  }), { status: 200, headers: { 'Content-Type': 'application/json' } })) as typeof fetch
})

function show(card: Card, props: { price?: number | null; feed?: string; now?: number } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><PlanCard card={card} now={props.now ?? NOW} price={props.price} feed={props.feed} /></QueryClientProvider>)
}

describe('PlanCard', () => {
  it('shows a green BUY with entry, stop, targets, money, size and the disclaimer', async () => {
    show(buyCard())
    const badge = screen.getByTestId('decision')
    expect(badge).toHaveTextContent('BUY')
    expect(badge.className).toContain('bg-up')
    expect(screen.getByText('Buy only if the price breaks above 1.0950')).toBeInTheDocument()
    expect(screen.getByText('1.0931 (19 pips)')).toBeInTheDocument()
    expect(screen.getByText(/−€8.70/)).toBeInTheDocument()
    expect(screen.getByText('1.0981 (+31 pips)')).toBeInTheDocument()
    expect(screen.getByText('Buy 0.05 lots')).toBeInTheDocument()
    expect(screen.getByText(/Close the trade by 21:30/)).toBeInTheDocument()
    expect(screen.getByText(/CPI m\/m/)).toBeInTheDocument()
    expect(screen.getByText('Analysis only, not financial advice. Always use a stop loss.')).toBeInTheDocument()
    expect(screen.getByText(/Last updated \d\d:\d\d:\d\d · next candle 10:00/)).toBeInTheDocument()
    expect(await screen.findByTestId('mini-chart')).toHaveTextContent('20:5')
  })

  it('labels GET READY (sky blue), SELL (red) and WAIT (amber)', () => {
    const { unmount } = show({ ...buyCard(), state: 'ready' })
    expect(screen.getByTestId('decision')).toHaveTextContent('GET READY')
    expect(screen.getByTestId('decision').className).toContain('bg-ready')
    unmount()
    const r2 = show({ ...buyCard(), action: 'SELL', direction: 'short' })
    expect(screen.getByTestId('decision').className).toContain('bg-down')
    r2.unmount()
    show(waitCard())
    expect(screen.getByTestId('decision')).toHaveTextContent('WAIT')
    expect(screen.getByTestId('decision').className).toContain('bg-wait')
  })

  it('shows the live distance to the entry from the WebSocket price', () => {
    show(buyCard(), { price: 1.0944 })
    expect(screen.getByTestId('live-distance')).toHaveTextContent('Price is 6 pips away from entry')
    expect(screen.getByTestId('dist-entry')).toHaveTextContent('6 pips away')
  })

  it('greys out and labels an old card, or one with a closed market', () => {
    const { container, unmount } = show(buyCard(), { now: NOW + 25 * 60_000 })
    expect(container.querySelector('article')!.className).toContain('opacity-60')
    expect(screen.getByRole('status')).toHaveTextContent(/Out of date/)
    unmount()
    show(buyCard(), { feed: 'closed' })
    expect(screen.getByRole('status')).toHaveTextContent('Market closed – prices are from the last session')
  })

  it('fresh card is not greyed', () => {
    const { container } = show(buyCard())
    expect(container.querySelector('article')!.className).not.toContain('opacity-60')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('WAIT shows the range, both scenarios and what it is waiting for', () => {
    show(waitCard())
    expect(screen.getByText('WAIT – stuck between 1.0912 and 1.0948.')).toBeInTheDocument()
    const sc = screen.getByTestId('scenarios')
    expect(within(sc).getByText('Buy if it breaks above 1.0950')).toBeInTheDocument()
    expect(within(sc).getByText('Sell if it breaks below 1.0910')).toBeInTheDocument()
    expect(within(sc).getByText(/60% likely/)).toBeInTheDocument()
    expect(screen.getByText("What I'm waiting for")).toBeInTheDocument()
  })

  it('main view has no indicator jargon; it appears only behind Show details', async () => {
    const user = userEvent.setup()
    const { container } = show(buyCard())
    const text = container.textContent ?? ''
    for (const j of JARGON) expect(text).not.toContain(j)
    expect(screen.queryByTestId('plan-details')).toBeNull()
    await user.click(screen.getByRole('button', { name: '▸ Show details' }))
    expect(screen.getByTestId('plan-details')).toHaveTextContent('RSI14 61')
  })

  it('explains terms with a tap-able glossary popover', async () => {
    const user = userEvent.setup()
    show(buyCard())
    await user.click(screen.getByRole('button', { name: 'Break-even: what is this?' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/stop loss to your entry price/)
  })
})
