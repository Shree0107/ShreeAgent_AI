// Chart indicators, computed in the browser so live candle updates redraw instantly.
// Each function mirrors analysis/indicators.py exactly (same smoothing and warm-up), verified by
// golden fixtures generated from the Python code (see indicators.test.ts). null = not enough data yet.

import type { Candle } from './api'

export type Series = (number | null)[]

/** pandas ewm(alpha, adjust=False, min_periods=n): starts at the first valid value, NaNs propagate as gaps. */
function ewm(x: Series, alpha: number, minPeriods: number): Series {
  const out: Series = new Array(x.length).fill(null)
  let prev: number | null = null
  let count = 0
  for (let i = 0; i < x.length; i++) {
    const v = x[i]
    if (v === null || Number.isNaN(v)) {
      out[i] = count >= minPeriods && prev !== null ? prev : null
      continue
    }
    prev = prev === null ? v : alpha * v + (1 - alpha) * prev
    count++
    out[i] = count >= minPeriods ? prev : null
  }
  return out
}

export const ema = (x: Series, n: number) => ewm(x, 2 / (n + 1), n)
export const wilder = (x: Series, n: number) => ewm(x, 1 / n, n)

export function sma(x: Series, n: number): Series {
  const out: Series = new Array(x.length).fill(null)
  for (let i = n - 1; i < x.length; i++) {
    let s = 0
    let ok = true
    for (let j = i - n + 1; j <= i; j++) {
      const v = x[j]
      if (v === null) {
        ok = false
        break
      }
      s += v
    }
    out[i] = ok ? s / n : null
  }
  return out
}

function rollingStd(x: Series, n: number): Series {
  const m = sma(x, n)
  return x.map((_, i) => {
    const mean = m[i]
    if (mean === null) return null
    let s = 0
    for (let j = i - n + 1; j <= i; j++) s += ((x[j] as number) - mean) ** 2
    return Math.sqrt(s / n) // ddof=0, like the Python code
  })
}

const closes = (c: Candle[]) => c.map((b) => b.close)

export function rsi(close: Series, n = 14): Series {
  const delta: Series = close.map((v, i) => (i === 0 || v === null || close[i - 1] === null ? null : v - (close[i - 1] as number)))
  const gain = wilder(delta.map((d) => (d === null ? null : Math.max(d, 0))), n)
  const loss = wilder(delta.map((d) => (d === null ? null : Math.max(-d, 0))), n)
  return gain.map((g, i) => {
    const l = loss[i]
    if (g === null || l === null) return null
    if (l === 0) return 100
    return 100 - 100 / (1 + g / l)
  })
}

export function macd(close: Series, fast = 12, slow = 26, signal = 9) {
  const f = ema(close, fast)
  const s = ema(close, slow)
  const line: Series = f.map((v, i) => (v === null || s[i] === null ? null : v - (s[i] as number)))
  const sig = ema(line, signal)
  const hist: Series = line.map((v, i) => (v === null || sig[i] === null ? null : v - (sig[i] as number)))
  return { macd: line, signal: sig, hist }
}

export function bollinger(close: Series, n = 20, k = 2) {
  const mid = sma(close, n)
  const sd = rollingStd(close, n)
  return {
    mid,
    upper: mid.map((m, i) => (m === null ? null : m + k * (sd[i] as number))),
    lower: mid.map((m, i) => (m === null ? null : m - k * (sd[i] as number))),
  }
}

export function trueRange(c: Candle[]): Series {
  return c.map((b, i) =>
    i === 0
      ? b.high - b.low
      : Math.max(b.high - b.low, Math.abs(b.high - c[i - 1].close), Math.abs(b.low - c[i - 1].close)),
  )
}

export const atr = (c: Candle[], n = 14) => wilder(trueRange(c), n)

export function stochastic(c: Candle[], k = 14, d = 3, smooth = 3) {
  const raw: Series = c.map((b, i) => {
    if (i < k - 1) return null
    let lo = Infinity
    let hi = -Infinity
    for (let j = i - k + 1; j <= i; j++) {
      lo = Math.min(lo, c[j].low)
      hi = Math.max(hi, c[j].high)
    }
    return hi - lo === 0 ? null : (100 * (b.close - lo)) / (hi - lo)
  })
  const kLine = sma(raw, smooth)
  return { k: kLine, d: sma(kLine, d) }
}

/** Rolling n-bar VWAP (daily/weekly bars) or session VWAP anchored at each UTC day (intraday). */
export function vwap(c: Candle[], intraday: boolean, n = 20): Series {
  const tp = c.map((b) => (b.high + b.low + b.close) / 3)
  if (intraday) {
    let day = -1
    let pv = 0
    let vol = 0
    return c.map((b, i) => {
      const dd = Math.floor(b.time / 86400)
      if (dd !== day) {
        day = dd
        pv = 0
        vol = 0
      }
      pv += tp[i] * b.volume
      vol += b.volume
      return vol > 0 ? pv / vol : null
    })
  }
  return c.map((_, i) => {
    if (i < n - 1) return null
    let pv = 0
    let vol = 0
    for (let j = i - n + 1; j <= i; j++) {
      pv += tp[j] * c[j].volume
      vol += c[j].volume
    }
    return vol > 0 ? pv / vol : null
  })
}

export function heikinAshi(c: Candle[]): Candle[] {
  const out: Candle[] = []
  c.forEach((b, i) => {
    const close = (b.open + b.high + b.low + b.close) / 4
    const open = i === 0 ? (b.open + b.close) / 2 : (out[i - 1].open + out[i - 1].close) / 2
    out.push({ time: b.time, open, close, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close), volume: b.volume })
  })
  return out
}

export const close = closes
