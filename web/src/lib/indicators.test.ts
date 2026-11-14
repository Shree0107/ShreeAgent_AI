import { describe, expect, it } from 'vitest'
import fixture from './__fixtures__/indicators.json'
import type { Candle } from './api'
import { atr, bollinger, close, ema, heikinAshi, macd, rsi, sma, stochastic, vwap, type Series } from './indicators'

const candles = fixture.candles as Candle[]
const exp = fixture.expected as Record<string, (number | null)[]>
const c = close(candles)

function same(actual: Series, expected: (number | null)[]) {
  expect(actual.length).toBe(expected.length)
  actual.forEach((v, i) => {
    const e = expected[i]
    if (e === null) expect(v, `index ${i} should be empty`).toBeNull()
    else {
      expect(v, `index ${i}`).not.toBeNull()
      expect(Math.abs((v as number) - e)).toBeLessThan(1e-9 * Math.max(1, Math.abs(e)))
    }
  })
}

describe('indicators match the Python engine exactly', () => {
  it('moving averages', () => {
    same(sma(c, 20), exp.sma_20)
    same(ema(c, 21), exp.ema_21)
    same(ema(c, 200), exp.ema_200)
  })
  it('RSI (Wilder)', () => same(rsi(c), exp.rsi_14))
  it('MACD', () => {
    const m = macd(c)
    same(m.macd, exp.macd)
    same(m.signal, exp.macd_signal)
    same(m.hist, exp.macd_hist)
  })
  it('Bollinger bands', () => {
    const b = bollinger(c)
    same(b.upper, exp.bb_upper)
    same(b.lower, exp.bb_lower)
  })
  it('ATR and stochastic', () => {
    same(atr(candles), exp.atr_14)
    const s = stochastic(candles)
    same(s.k, exp.stoch_k)
    same(s.d, exp.stoch_d)
  })
  it('rolling VWAP', () => same(vwap(candles, false), exp.vwap))
})

describe('Heikin Ashi', () => {
  it('follows the standard formulas', () => {
    const ha = heikinAshi(candles)
    const b = candles[1]
    expect(ha[1].close).toBeCloseTo((b.open + b.high + b.low + b.close) / 4, 12)
    expect(ha[1].open).toBeCloseTo((ha[0].open + ha[0].close) / 2, 12)
    ha.forEach((h, i) => {
      expect(h.high).toBeGreaterThanOrEqual(Math.max(h.open, h.close, candles[i].high) - 1e-12)
      expect(h.low).toBeLessThanOrEqual(Math.min(h.open, h.close, candles[i].low) + 1e-12)
    })
  })
})
