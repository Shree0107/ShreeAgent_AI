// History (closing prices) + forecast median + shaded 50% and 80% ranges.
import { ColorType, LineSeries, LineStyle, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import type { Candle } from '../../lib/api'
import { toUnix, type ForecastData } from '../../lib/forecast'
import { BandsPrimitive } from './BandsPrimitive'

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

/** '#3b82f6' or 'rgb(...)' -> rgba with the given alpha. */
export function withAlpha(color: string, alpha: number): string {
  const hex = color.match(/^#([0-9a-f]{6})$/i)
  if (hex) {
    const n = parseInt(hex[1], 16)
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
  }
  const rgb = color.match(/^rgba?\(([^)]+)\)$/)
  if (rgb) {
    const [r, g, b] = rgb[1].split(',').map((x) => x.trim())
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }
  return color
}

interface Props {
  candles: Candle[]
  forecast: ForecastData | null
  decimals: number
  intraday: boolean
  theme: string
  outdated: boolean
}

const t = (x: number) => x as UTCTimestamp

export function ForecastChart({ candles, forecast, decimals, intraday, theme, outdated }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const s = useRef<Record<string, ISeriesApi<'Line'>>>({})
  const bands = useRef(new BandsPrimitive())

  useEffect(() => {
    if (!box.current) return
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: css('--muted'), fontSize: 12,
                attributionLogo: true },
      grid: { vertLines: { color: css('--grid') }, horzLines: { color: css('--grid') } },
      rightPriceScale: { borderColor: css('--border') },
      timeScale: { borderColor: css('--border'), timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
    })
    chartRef.current = chart
    const fmt = { type: 'price' as const, precision: decimals, minMove: 10 ** -decimals }
    const quiet = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: fmt }
    const accent = css('--accent')
    s.current = {
      history: chart.addSeries(LineSeries, { color: css('--text'), lineWidth: 2, priceFormat: fmt, priceLineVisible: false }),
      // band edges: faint lines that also make the price scale fit the whole range
      q90: chart.addSeries(LineSeries, { ...quiet, color: withAlpha(accent, 0.35), lineWidth: 1 }),
      q10: chart.addSeries(LineSeries, { ...quiet, color: withAlpha(accent, 0.35), lineWidth: 1 }),
      median: chart.addSeries(LineSeries, { color: accent, lineWidth: 2, lineStyle: LineStyle.Dashed, priceFormat: fmt,
                                           priceLineVisible: false }),
    }
    s.current.median.attachPrimitive(bands.current)
    return () => {
      s.current.median?.detachPrimitive(bands.current)
      chart.remove()
      chartRef.current = null
      s.current = {}
    }
  }, [decimals, intraday, theme])

  useEffect(() => {
    const ser = s.current
    if (!ser.history) return
    const last = forecast ? toUnix(forecast.last_bar_time) : Infinity
    // history up to the candle the forecast was built on (plus anything newer, so the user sees what happened since)
    ser.history.setData(candles.map((c) => ({ time: t(c.time), value: c.close })))
    if (!forecast) {
      for (const k of ['median', 'q10', 'q90'] as const) ser[k].setData([])
      bands.current.set([])
      chartRef.current?.timeScale().fitContent()
      return
    }
    const times = forecast.dates.map(toUnix)
    const start = { time: t(last), value: forecast.last_close }
    const path = (v: number[]) => [start, ...times.map((x, i) => ({ time: t(x), value: v[i] }))]
    ser.median.setData(path(forecast.median))
    ser.q10.setData(path(forecast.q10))
    ser.q90.setData(path(forecast.q90))
    const accent = css('--accent')
    const pts = (lo: number[], hi: number[]) => [
      { time: last, lo: forecast.last_close, hi: forecast.last_close },
      ...times.map((x, i) => ({ time: x, lo: lo[i], hi: hi[i] })),
    ]
    bands.current.set([
      { points: pts(forecast.q10, forecast.q90), fill: withAlpha(accent, outdated ? 0.08 : 0.14) },
      { points: pts(forecast.q25, forecast.q75), fill: withAlpha(accent, outdated ? 0.12 : 0.24) },
    ])
    // show the recent past and the whole forecast
    const ts = chartRef.current?.timeScale()
    const n = candles.length
    if (ts && n) ts.setVisibleLogicalRange({ from: Math.max(0, n - Math.max(60, forecast.median.length * 3)), to: n + forecast.median.length + 2 })
  }, [candles, forecast, outdated, decimals, intraday, theme])

  return <div ref={box} className={`h-full w-full ${outdated ? 'opacity-60' : ''}`} data-testid="forecast-chart-canvas" />
}
