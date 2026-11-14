import { describe, expect, it } from 'vitest'
import { overlayShapes, regimeText } from './overlay'

const ov = {
  zones: [{ kind: 'support', low: 1.09, high: 1.091, t_start: 100, touches: 4, strength: 6 }],
  trendlines: [{ kind: 'resistance', t1: 100, p1: 1.12, end_time: 900, end_price: 1.1, touches: 3 }],
  channels: [],
  fibonacci: { from: { time: 100, price: 1.08 }, to: { time: 500, price: 1.12 },
               retracements: [{ ratio: 0.5, price: 1.1 }, { ratio: 0.618, price: 1.0953 }] },
  liquidity: [{ kind: 'pdh', price: 1.105, t_start: 800, label: 'Previous day high', swept: true },
              { kind: 'round', price: 1.1, t_start: 0, label: 'Round number' }],
  sweeps: [{ level_kind: 'pdh', level: 1.105, direction: 'up', time: 850 }],
  swings: [{ kind: 'H', label: 'LH', time: 400, price: 1.11 }, { kind: 'L', label: '', time: 300, price: 1.09 }],
  structure: { events: [{ kind: 'CHoCH', direction: 'down', level: 1.095, swing_time: 300, time: 600 }] },
  order_blocks: [{ kind: 'bear_ob', low: 1.108, high: 1.11, t_start: 450 }], fvgs: [], supply_demand: [],
  regime: { state: 'sideways', squeeze: true, range: { low: 1.0912, high: 1.0948 } },
  trade_plan: { action: 'SELL', entry_low: 1.1, entry_high: 1.102, stop: 1.106, target1: 1.094, target2: 1.09,
                generated_at: '2026-11-13T09:00:00+00:00' },
}

describe('AI analysis overlay shapes', () => {
  it('only draws the chosen categories', () => {
    expect(overlayShapes(ov, [])).toEqual([])
    const z = overlayShapes(ov, ['zones'])
    expect(z).toHaveLength(1)
    expect(z[0]).toMatchObject({ kind: 'box', t2: 'right', label: 'Support (4 touches)' })
  })
  it('trade plan: entry zone box + stop + two targets', () => {
    const p = overlayShapes(ov, ['plan'])
    expect(p.map((s) => s.kind)).toEqual(['box', 'hline', 'hline', 'hline'])
    expect(p.filter((s) => s.kind === 'hline').map((s) => (s as { price: number }).price)).toEqual([1.106, 1.094, 1.09])
  })
  it('structure labels only labelled swings, plus BOS/CHoCH lines', () => {
    const s = overlayShapes(ov, ['structure'])
    expect(s.filter((x) => x.kind === 'text')).toHaveLength(1)
    expect(s.some((x) => x.kind === 'line' && x.label === 'CHoCH')).toBe(true)
  })
  it('liquidity marks swept levels and stop hunts', () => {
    const l = overlayShapes(ov, ['liquidity'])
    expect(l.some((x) => x.kind === 'hline' && x.label === 'Previous day high (swept)')).toBe(true)
    expect(l.some((x) => x.kind === 'text' && x.text.includes('stop hunt'))).toBe(true)
  })
  it('everything together, and nothing for an error payload', () => {
    expect(overlayShapes(ov, ['plan', 'lines', 'zones', 'fib', 'liquidity', 'smc', 'structure']).length).toBeGreaterThan(10)
    expect(overlayShapes({ error: 'no data' }, ['zones'])).toEqual([])
  })
  it('regime in plain words', () => {
    expect(regimeText(ov, 4)).toBe('Sideways between 1.0912 and 1.0948 · volatility squeeze (a breakout often follows)')
    expect(regimeText({ regime: { state: 'trending_down', squeeze: false } }, 5)).toBe('Trending down')
  })
})
