import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { buyCard, waitCard } from '../lib/__fixtures__/plans'

vi.mock('../components/chart/PriceChart', () => ({ PriceChart: () => <div data-testid="mini-chart" /> }))
const topics: string[] = []
vi.mock('../lib/ws', async () => {
  const { create } = await import('zustand')
  return { getSocket: () => ({ on: (t: string) => { topics.push(t); return () => {} } }), useConnection: create(() => ({ state: 'live' })) }
})

const { default: TradePlanTab } = await import('./TradePlanTab')
const calls: string[] = []

beforeEach(() => {
  localStorage.clear()
  calls.length = 0
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url)
    calls.push(u)
    const now = new Date().toISOString()
    const body = u.startsWith('/api/plans') ? {
      cards: [{ ...waitCard(), symbol: 'GBP/USD', generated_at: now }, { ...buyCard(), generated_at: now }],
      generated_at: now, refresh_job: null, config: { min_rr: 1.5, flat_by: '21:30', no_new_entries_after: '18:00', timezone: 'Europe/Berlin' },
      account: { size: 1000, risk_pct: 1, currency: 'EUR' } }
      : u.startsWith('/api/signals') ? { cards: [{ symbol: 'EUR/USD', action: 'PENDING', message: 'Analysing for the first time…' }] }
      : u.startsWith('/api/settings') ? { account: { size: 2500, risk_pct: 0.5, currency: 'EUR' } }
      : { candles: [], symbol: 'EUR/USD', tf: '15m', source: 'x', has_more: false }
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
})

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><TradePlanTab /></QueryClientProvider>)
}

describe('Trade Plan tab', () => {
  it('lists cards strongest first, filters them, sizes with settings defaults and subscribes to plan topics', async () => {
    const user = userEvent.setup()
    renderTab()
    await waitFor(() => expect(screen.getAllByTestId('plan-card')).toHaveLength(2))
    expect(screen.getAllByTestId('plan-card')[0]).toHaveAttribute('aria-label', 'EUR/USD BUY')
    await waitFor(() => expect(calls.some((c) => c.includes('account=2500') && c.includes('risk=0.5'))).toBe(true))
    expect(topics).toContain('plan:EUR/USD')
    expect(topics).toContain('plan_event')
    await user.click(screen.getByRole('button', { name: 'Wait' }))
    expect(screen.getAllByTestId('plan-card')).toHaveLength(1)
    expect(screen.getByTestId('plan-card')).toHaveAttribute('aria-label', 'GBP/USD WAIT')
    await user.click(screen.getByRole('button', { name: 'Get ready' }))
    expect(screen.getByText('No cards match this filter.')).toBeInTheDocument()
    expect(screen.getByText(/no new entries after 18:00, everything closed by 21:30/)).toBeInTheDocument()
  })

  it('switches to the daily swing cards', async () => {
    const user = userEvent.setup()
    renderTab()
    await user.click(screen.getByRole('button', { name: 'Swing (daily)' }))
    expect(await screen.findByTestId('swing-card')).toHaveTextContent('Analysing for the first time…')
    expect(calls.some((c) => c.startsWith('/api/signals'))).toBe(true)
  })
})
