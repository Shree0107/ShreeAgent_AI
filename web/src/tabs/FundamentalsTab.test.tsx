import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useApp } from '../lib/store'
import FundamentalsTab, { symbolCurrencies } from './FundamentalsTab'

vi.mock('../lib/ws', async () => {
  const { create } = await import('zustand')
  return { getSocket: () => ({ on: () => () => {} }), useConnection: create(() => ({ state: 'live' })) }
})

const inHours = (h: number) => new Date(Date.now() + h * 3600_000).toISOString()
const ev = (o: Record<string, unknown>) => ({
  currency: 'USD', impact: 'high', forecast: '', previous: '', actual: '', actual_source: '', source: 'forexfactory',
  time_exact: true, major: false, past: false, type: 'other', surprise: null, affects_symbol: true, meaning: '', ...o,
})
const calendar = {
  range: 'today', range_start: '', range_end: '', tz: 'UTC', now: '', feed_ok: true, notes: [],
  source: 'ForexFactory weekly feed', focus_currencies: ['EUR', 'USD'],
  events: [
    ev({ time: inHours(-2), title: 'CPI m/m', plain_title: 'US inflation', major: true, past: true, actual: '0.5%',
         forecast: '0.3%', previous: '0.4%', surprise: 'higher', actual_source: 'FRED',
         meaning: 'Came in higher than expected (0.5% vs 0.3% forecast) → usually makes the US dollar stronger → EUR/USD tends to fall.' }),
    ev({ time: inHours(3), currency: 'EUR', impact: 'medium', title: 'German ZEW Economic Sentiment',
         plain_title: 'euro-area business activity', meaning: 'Higher euro-area business activity usually makes the euro stronger → EUR/USD tends to rise.' }),
  ],
  next_major: ev({ time: inHours(2), title: 'Federal Funds Rate', plain_title: 'US interest-rate decision', major: true,
                   meaning: 'A higher US interest rate usually makes the US dollar stronger → EUR/USD tends to fall.' }),
}
const banks = {
  tooltip: 'An estimate, not a market price.', notes: ['Rates come from FRED.'], source: 'FRED',
  banks: [
    { currency: 'USD', bank: 'Federal Reserve', short: 'Fed', policy_rate: 3.75, rate_as_of: '2026-11-13',
      next_meeting: { date: '2026-12-09', time: null, title: 'FOMC', source: 'config/events.yaml' },
      expectation: { lean: 'cut', label: 'leaning to cut (estimate)', score: -1, reasons: ['It cut rates.'], inputs: 3 } },
    { currency: 'CHF', bank: 'Swiss National Bank', short: 'SNB', policy_rate: null, next_meeting: null,
      next_meeting_text: 'date not in calendar file', expectation: { lean: 'unknown', label: 'not enough data', score: 0, reasons: [], inputs: 0 } },
  ],
}
const strength = {
  tf: '1d', pairs: {}, missing_pairs: ['NZD/CHF'], as_of: inHours(0), sources: ['yfinance'], live: false,
  notes: ['Prices from Yahoo are delayed, not live.'],
  currencies: [
    { currency: 'USD', name: 'the US dollar', strength: 0.42, n_pairs: 7, rank: 1 },
    { currency: 'EUR', name: 'the euro', strength: 0.05, n_pairs: 7, rank: 2 },
    { currency: 'JPY', name: 'the Japanese yen', strength: -0.6, n_pairs: 7, rank: 3 },
  ],
}
const news = {
  symbol: 'EUR/USD', label: 'neutral', score: 0, n_articles: 1, method: 'lexicon',
  headlines: [{ title: 'Euro slips as Fed stays hawkish', source: 'Wire', date: '2026-11-14', url: 'http://x', sentiment: -0.5, label: 'negative' }],
}
const bias = {
  symbol: 'EUR/USD', kind: 'fx', bias: 'bearish', score: -50, headline: 'Bearish', estimate: true, source: 'FRED',
  horizon: 'Big-picture view.', why: ['The big picture favours the US dollar, so EUR/USD leans down.'],
}
const stock = {
  symbol: 'AAPL', name: 'Apple Inc.', sector: 'Technology', price: 200, currency: 'USD', source: 'yfinance',
  facts: [{ key: 'sales', label: 'Sales growth', value: '+12%', text: "The company's sales grew 12% over the last year.", tone: 'good', tip: '' }],
  earnings: { date: '2027-01-29', days_away: 76, text: 'Next earnings report: 2027-01-29 (in 76 days).' },
  analysts: { recommendation: 'buy', target: 230, upside_pct: 15, text: "Analysts' average rating: buy." },
}

let calls: string[] = []
function mockFetch(overrides: Record<string, () => Response> = {}) {
  calls = []
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url)
    calls.push(u)
    for (const [k, fn] of Object.entries(overrides)) if (u.startsWith(k)) return fn()
    const body = u.startsWith('/api/fund/calendar') ? calendar
      : u.startsWith('/api/fund/central-banks') ? banks
      : u.startsWith('/api/fund/strength') ? strength
      : u.startsWith('/api/fund/news-summary') ? { symbol: 'EUR/USD', enabled: false, note: 'AI summaries are off (set ANTHROPIC_API_KEY in .env to turn them on).', items: [{ title: news.headlines[0].title, summary: null }] }
      : u.startsWith('/api/fund/news') ? news
      : u.startsWith('/api/fund/bias') ? (u.includes('AAPL') ? { ...bias, symbol: 'AAPL', kind: 'stock', bias: 'bullish', headline: 'Bullish', why: ['Numbers look healthy.'] } : bias)
      : u.startsWith('/api/fund/stock') ? stock : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><FundamentalsTab /></QueryClientProvider>)
}

describe('Fundamentals tab', () => {
  beforeEach(() => {
    localStorage.clear()
    useApp.setState({ symbol: 'EUR/USD' })
    mockFetch()
  })

  it('shows the countdown banner and the calendar with meaning lines', async () => {
    renderTab()
    const banner = screen.getByTestId('next-event')
    await waitFor(() => expect(banner).toHaveTextContent('US interest-rate decision'))
    expect(within(banner).getByLabelText('countdown').textContent).toMatch(/^in 1:5\d:\d\d$/)
    const rows = await screen.findAllByTestId('cal-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveClass('opacity-50') // past event dimmed
    expect(rows[0]).toHaveTextContent('0.5%')
    expect(rows[0]).toHaveTextContent('EUR/USD tends to fall')
    expect(calls.find((c) => c.startsWith('/api/fund/calendar'))).toContain('currencies=EUR%2CUSD')
  })

  it('changes filters: range, currency and impact', async () => {
    const user = userEvent.setup()
    renderTab()
    await screen.findAllByTestId('cal-row')
    await user.click(screen.getByRole('button', { name: 'This week' }))
    await user.selectOptions(screen.getByLabelText('Currency'), 'all')
    await user.click(screen.getByRole('button', { name: 'Low' }))
    await waitFor(() => {
      const last = calls.filter((c) => c.startsWith('/api/fund/calendar')).at(-1)!
      expect(last).toContain('range=week')
      expect(last).not.toContain('currencies=')
      expect(last).toContain('impact=high%2Cmedium')
      expect(last).not.toContain('holiday')
    })
  })

  it('shows bias, central banks, strength and news', async () => {
    renderTab()
    expect(await screen.findByTestId('bias-label')).toHaveTextContent('Bearish')
    const bankRows = await screen.findAllByTestId('bank-row')
    expect(bankRows[0]).toHaveTextContent('3.75%')
    expect(bankRows[0]).toHaveTextContent('leaning to cut (estimate)')
    expect(bankRows[1]).toHaveTextContent('date not in calendar file')
    const sRows = await screen.findAllByTestId('strength-row')
    expect(sRows.map((r) => r.textContent?.slice(0, 3))).toEqual(['USD', 'EUR', 'JPY'])
    expect(screen.getByTestId('strength')).toHaveTextContent('delayed, not live')
    expect(await screen.findByText('Euro slips as Fed stays hawkish')).toBeInTheDocument()
    expect(screen.getByLabelText('negative news')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('news')).toHaveTextContent('ANTHROPIC_API_KEY'))
    expect(screen.queryByTestId('stock')).toBeNull() // forex: no company numbers
  })

  it('one failing section does not break the others', async () => {
    mockFetch({ '/api/fund/strength': () => new Response(JSON.stringify({ detail: 'Yahoo down' }), { status: 502 }) })
    renderTab()
    expect(await within(screen.getByTestId('strength')).findByRole('alert')).toHaveTextContent('Yahoo down')
    expect(await screen.findByTestId('bias-label')).toHaveTextContent('Bearish')
    expect(await screen.findAllByTestId('cal-row')).toHaveLength(2)
  })

  it('shows company numbers for a stock', async () => {
    useApp.setState({ symbol: 'AAPL' })
    renderTab()
    expect(await screen.findByText("The company's sales grew 12% over the last year.")).toBeInTheDocument()
    expect(screen.getByTestId('stock')).toHaveTextContent('Next earnings report: 2027-01-29')
    expect(await screen.findByTestId('bias-label')).toHaveTextContent('Bullish')
  })

  it('maps symbols to the currencies that move them', () => {
    expect(symbolCurrencies('EUR/USD')).toEqual(['EUR', 'USD'])
    expect(symbolCurrencies('XAU/USD')).toEqual(['USD'])
    expect(symbolCurrencies('AAPL')).toEqual(['USD'])
    expect(symbolCurrencies('RELIANCE.NS')).toEqual(['INR'])
  })
})
