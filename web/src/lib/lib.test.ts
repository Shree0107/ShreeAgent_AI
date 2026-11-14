import { describe, expect, it } from 'vitest'
import { decimalsFor, fmtCountdown, fmtPct, fmtPrice } from './format'
import { mergeCandles } from './useCandles'
import { backoffMs } from './ws'

const bar = (time: number, close = 1) => ({ time, open: close, high: close, low: close, close, volume: 0 })

describe('formatting', () => {
  it('prices and percentages', () => {
    expect(fmtPrice(1.094123, 5)).toBe('1.09412')
    expect(fmtPrice(null)).toBe('–')
    expect(fmtPct(0.183)).toBe('+0.18%')
    expect(fmtPct(-1.5)).toBe('-1.50%')
  })
  it('precision follows the market', () => {
    expect(decimalsFor('EUR/USD', 1.09)).toBe(5)
    expect(decimalsFor('USD/JPY', 151)).toBe(3)
    expect(decimalsFor('XAU/USD', 2400)).toBe(2)
    expect(decimalsFor('AAPL', 230)).toBe(2)
  })
  it('countdown', () => {
    expect(fmtCountdown(65)).toBe('1:05')
    expect(fmtCountdown(3725)).toBe('1:02:05')
  })
})

describe('candle merging (paging and live updates)', () => {
  it('dedupes by time, newest data wins, stays sorted', () => {
    const merged = mergeCandles([bar(3), bar(1), bar(2, 5)], [bar(2, 9), bar(4)])
    expect(merged.map((b) => b.time)).toEqual([1, 2, 3, 4])
    expect(merged[1].close).toBe(9)
  })
})

describe('reconnect backoff', () => {
  it('grows exponentially with jitter and is capped', () => {
    expect(backoffMs(0, 500, 15000, () => 0)).toBe(250)
    expect(backoffMs(0, 500, 15000, () => 1)).toBe(500)
    expect(backoffMs(3, 500, 15000, () => 1)).toBe(4000)
    expect(backoffMs(20, 500, 15000, () => 1)).toBe(15000)
  })
})

describe('connection / feed status shown in the top bar', async () => {
  const { describeStatus } = await import('./live')
  it('never shows stale or delayed data as live', () => {
    expect(describeStatus('live', 'live', 'oanda').label).toBe('Live')
    expect(describeStatus('live', 'delayed', 'yfinance').label).toBe('Delayed')
    expect(describeStatus('live', 'stale', 'oanda')).toMatchObject({ label: 'Stale', tone: 'down' })
    expect(describeStatus('live', 'closed', 'oanda').label).toBe('Market closed')
    expect(describeStatus('reconnecting', 'live', 'oanda').label).toBe('Reconnecting')   // server link first
    expect(describeStatus('offline', 'live', 'oanda').label).toBe('Offline')
    expect(describeStatus('live', undefined, '').label).toBe('Delayed')
  })
})
