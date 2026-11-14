// The "AI analysis" overlay: turns the backend's /api/overlay JSON into simple shapes the chart can draw.
// Pure functions (unit-tested); the drawing happens in components/chart/OverlayPrimitive.ts.

export type OverlayCategory = 'lines' | 'zones' | 'fib' | 'liquidity' | 'smc' | 'structure' | 'plan'

export const OVERLAY_CATEGORIES: { id: OverlayCategory; label: string; help: string }[] = [
  { id: 'plan', label: 'Trade plan', help: 'Entry zone, stop loss and targets of the current signal' },
  { id: 'lines', label: 'Trendlines & channels', help: 'Lines through swing highs/lows that price respected' },
  { id: 'zones', label: 'Support & resistance', help: 'Price areas touched several times (stronger = more touches)' },
  { id: 'structure', label: 'Market structure', help: 'Higher highs / lower lows, breaks of structure (BOS) and changes of character (CHoCH)' },
  { id: 'fib', label: 'Fibonacci', help: 'Retracement levels of the last big swing' },
  { id: 'liquidity', label: 'Liquidity', help: 'Previous day/week highs & lows, Asian range, equal highs/lows, round numbers, stop hunts' },
  { id: 'smc', label: 'Order blocks, gaps, supply/demand', help: 'Where big orders likely sit: order blocks, fair value gaps, supply & demand zones' },
]

export const DEFAULT_CATEGORIES: OverlayCategory[] = ['plan', 'lines', 'zones', 'structure']

export interface TP {
  time: number | 'right' // 'right' = extend to the right edge
  price: number
}

export type OShape =
  | { kind: 'line'; a: TP; b: TP; color: string; dash?: boolean; width?: number; label?: string }
  | { kind: 'hline'; price: number; from?: number; color: string; dash?: boolean; label?: string; width?: number }
  | { kind: 'box'; t1: number; t2: number | 'right'; p1: number; p2: number; fill: string; stroke?: string; label?: string }
  | { kind: 'text'; at: TP; text: string; color: string; below?: boolean }

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Overlay = Record<string, any>

export const OCOLORS = {
  up: '#22c55e', down: '#ef4444', neutral: '#94a3b8', accent: '#3b82f6', fib: '#a855f7', liq: '#eab308',
  entry: '#3b82f6', stop: '#ef4444', target: '#22c55e',
}

const alpha = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

export function overlayShapes(o: Overlay | null | undefined, cats: OverlayCategory[]): OShape[] {
  if (!o || o.error) return []
  const on = (c: OverlayCategory) => cats.includes(c)
  const out: OShape[] = []

  if (on('zones')) {
    for (const z of o.zones ?? []) {
      const sup = z.kind === 'support'
      const strong = Math.min(1, (z.strength ?? 1) / 10)
      out.push({ kind: 'box', t1: z.t_start, t2: 'right', p1: z.low, p2: z.high,
                 fill: alpha(sup ? OCOLORS.up : OCOLORS.down, 0.08 + 0.12 * strong),
                 label: `${sup ? 'Support' : 'Resistance'} (${z.touches} touches)` })
    }
  }
  if (on('smc')) {
    const colorOf: Record<string, [string, string]> = {
      bull_ob: [OCOLORS.up, 'Bullish order block'], bear_ob: [OCOLORS.down, 'Bearish order block'],
      bull_fvg: [OCOLORS.up, 'Gap (FVG) up'], bear_fvg: [OCOLORS.down, 'Gap (FVG) down'],
      demand: [OCOLORS.up, 'Demand zone'], supply: [OCOLORS.down, 'Supply zone'],
    }
    for (const z of [...(o.order_blocks ?? []), ...(o.fvgs ?? []), ...(o.supply_demand ?? [])]) {
      const [c, label] = colorOf[z.kind] ?? [OCOLORS.neutral, z.kind]
      out.push({ kind: 'box', t1: z.t_start, t2: 'right', p1: z.low, p2: z.high, fill: alpha(c, 0.1), stroke: alpha(c, 0.6), label })
    }
  }
  if (on('lines')) {
    for (const l of o.trendlines ?? []) {
      const c = l.kind === 'support' ? OCOLORS.up : OCOLORS.down
      out.push({ kind: 'line', a: { time: l.t1, price: l.p1 }, b: { time: l.end_time, price: l.end_price }, color: c, width: 1.5,
                 label: `Trendline (${l.touches} touches)` })
    }
    for (const ch of o.channels ?? []) {
      const b = ch.base
      out.push({ kind: 'line', a: { time: b.t1, price: b.p1 + ch.offset }, b: { time: b.end_time, price: b.end_price + ch.offset },
                 color: OCOLORS.accent, dash: true, label: `Channel ${ch.direction}` })
    }
  }
  if (on('fib') && o.fibonacci) {
    const f = o.fibonacci
    out.push({ kind: 'line', a: { time: f.from.time, price: f.from.price }, b: { time: f.to.time, price: f.to.price }, color: OCOLORS.fib, dash: true })
    for (const r of f.retracements) {
      out.push({ kind: 'hline', price: r.price, from: f.to.time, color: OCOLORS.fib, dash: true, label: `Fib ${(r.ratio * 100).toFixed(1)}%` })
    }
  }
  if (on('liquidity')) {
    for (const lv of o.liquidity ?? []) {
      if (lv.kind === 'round') continue
      out.push({ kind: 'hline', price: lv.price, from: lv.t_start || undefined, color: OCOLORS.liq, dash: true,
                 label: `${lv.label}${lv.swept ? ' (swept)' : ''}` })
    }
    for (const lv of (o.liquidity ?? []).filter((x: any) => x.kind === 'round')) {
      out.push({ kind: 'hline', price: lv.price, color: alpha(OCOLORS.neutral, 0.5), dash: true, label: 'Round number' })
    }
    for (const s of o.sweeps ?? []) {
      out.push({ kind: 'text', at: { time: s.time, price: s.level }, text: s.direction === 'up' ? '⚡ stop hunt ↓' : '⚡ stop hunt ↑',
                 color: OCOLORS.liq, below: s.direction === 'down' })
    }
  }
  if (on('structure')) {
    for (const s of o.swings ?? []) {
      if (!s.label) continue
      out.push({ kind: 'text', at: { time: s.time, price: s.price }, text: s.label,
                 color: s.label === 'HH' || s.label === 'HL' ? OCOLORS.up : OCOLORS.down, below: s.kind === 'L' })
    }
    for (const e of o.structure?.events ?? []) {
      out.push({ kind: 'line', a: { time: e.swing_time, price: e.level }, b: { time: e.time, price: e.level },
                 color: e.direction === 'up' ? OCOLORS.up : OCOLORS.down, dash: true, label: e.kind })
    }
  }
  if (on('plan') && o.trade_plan) {
    const p = o.trade_plan
    out.push({ kind: 'box', t1: Date.parse(p.generated_at) / 1000, t2: 'right', p1: p.entry_low, p2: p.entry_high,
               fill: alpha(OCOLORS.entry, 0.15), stroke: OCOLORS.entry, label: `${p.action} entry zone` })
    out.push({ kind: 'hline', price: p.stop, color: OCOLORS.stop, width: 2, label: 'Stop loss' })
    out.push({ kind: 'hline', price: p.target1, color: OCOLORS.target, width: 2, label: 'Target 1' })
    out.push({ kind: 'hline', price: p.target2, color: OCOLORS.target, dash: true, label: 'Target 2' })
  }
  return out
}

/** One plain sentence describing the market regime, for the chart's info line. */
export function regimeText(o: Overlay | null | undefined, decimals: number): string | null {
  const r = o?.regime
  if (!r) return null
  const base = r.state === 'trending_up' ? 'Trending up' : r.state === 'trending_down' ? 'Trending down'
    : r.range ? `Sideways between ${r.range.low.toFixed(decimals)} and ${r.range.high.toFixed(decimals)}` : 'Sideways'
  return r.squeeze ? `${base} · volatility squeeze (a breakout often follows)` : base
}
