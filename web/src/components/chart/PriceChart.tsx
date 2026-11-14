import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart,
  type IChartApi, type ISeriesApi, type LogicalRange, type MouseEventParams, type SeriesType, type Time, type UTCTimestamp,
} from 'lightweight-charts'
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import type { Candle } from '../../lib/api'
import { fmtPrice } from '../../lib/format'
import * as I from '../../lib/indicators'
import type { ChartType, IndicatorId } from '../../lib/store'

export interface PriceChartHandle {
  screenshot: () => HTMLCanvasElement | null
  chart: () => IChartApi | null
  mainSeries: () => ISeriesApi<SeriesType> | null
}

interface Props {
  candles: Candle[]
  chartType: ChartType
  indicators: IndicatorId[]
  decimals: number
  intraday: boolean
  hasVolume: boolean
  theme: string
  onNeedMore?: () => void
}

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

const OVERLAY_COLORS: Record<string, string> = {
  ema21: '#3b82f6', ema50: '#f97316', ema200: '#a855f7', sma20: '#14b8a6', sma50: '#eab308', vwap: '#ec4899',
}

const t = (x: number) => x as UTCTimestamp
const line = (c: Candle[], v: I.Series) =>
  c.map((b, i) => (v[i] === null ? { time: t(b.time) } : { time: t(b.time), value: v[i] as number }))

/** Indicator panes in a fixed order; each gets its own pane below the price. */
/** 0-100 oscillators (RSI, stochastic) need only one decimal. */
const PCT = { type: 'price' as const, precision: 1, minMove: 0.1 }

const PANE_ORDER: IndicatorId[] = ['volume', 'rsi', 'macd', 'stoch', 'atr']

export const PriceChart = forwardRef<PriceChartHandle, Props>(function PriceChart(
  { candles, chartType, indicators, decimals, intraday, hasVolume, theme, onNeedMore }, ref,
) {
  const box = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const mainRef = useRef<ISeriesApi<SeriesType> | null>(null)
  const seriesRef = useRef<Record<string, ISeriesApi<SeriesType>>>({})
  const needMoreRef = useRef(onNeedMore)
  needMoreRef.current = onNeedMore
  const [legend, setLegend] = useState<Candle | null>(null)

  const panes = useMemo(
    () => PANE_ORDER.filter((p) => indicators.includes(p) && (p !== 'volume' || hasVolume)),
    [indicators, hasVolume],
  )
  const config = `${chartType}|${indicators.slice().sort().join(',')}|${panes.join(',')}|${decimals}|${theme}`

  useImperativeHandle(ref, () => ({
    screenshot: () => chartRef.current?.takeScreenshot(true) ?? null,
    chart: () => chartRef.current,
    mainSeries: () => mainRef.current,
  }))

  // (Re)build the chart when its structure changes.
  useEffect(() => {
    if (!box.current) return
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: css('--muted'), fontSize: 12,
                attributionLogo: true, panes: { separatorColor: css('--border'), enableResize: true } },
      grid: { vertLines: { color: css('--grid') }, horzLines: { color: css('--grid') } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: css('--border') },
      timeScale: { borderColor: css('--border'), timeVisible: intraday, secondsVisible: false, rightOffset: 6 },
    })
    chartRef.current = chart
    const up = css('--up')
    const down = css('--down')
    const fmt = { type: 'price' as const, precision: decimals, minMove: 10 ** -decimals }

    const s: Record<string, ISeriesApi<SeriesType>> = {}
    if (chartType === 'line') {
      s.main = chart.addSeries(LineSeries, { color: css('--accent'), lineWidth: 2, priceFormat: fmt })
    } else {
      s.main = chart.addSeries(CandlestickSeries, {
        upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down,
        priceFormat: fmt,
      })
    }
    for (const id of ['ema21', 'ema50', 'ema200', 'sma20', 'sma50', 'vwap'] as const) {
      if (indicators.includes(id) && (id !== 'vwap' || hasVolume)) {
        s[id] = chart.addSeries(LineSeries, { color: OVERLAY_COLORS[id], lineWidth: 1, priceLineVisible: false,
                                              lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: fmt })
      }
    }
    if (indicators.includes('bb')) {
      for (const k of ['bbU', 'bbL', 'bbM'] as const) {
        s[k] = chart.addSeries(LineSeries, { color: css('--muted'), lineWidth: 1,
                                             lineStyle: k === 'bbM' ? LineStyle.Dotted : LineStyle.Solid,
                                             priceLineVisible: false, lastValueVisible: false,
                                             crosshairMarkerVisible: false, priceFormat: fmt })
      }
    }
    panes.forEach((p, i) => {
      const pane = i + 1
      if (p === 'volume') s.volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false }, pane)
      if (p === 'rsi') {
        s.rsi = chart.addSeries(LineSeries, { color: '#a855f7', lineWidth: 1, priceLineVisible: false, priceFormat: PCT }, pane)
        for (const lvl of [70, 30]) s.rsi.createPriceLine({ price: lvl, color: css('--muted'), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false })
      }
      if (p === 'macd') {
        s.macdH = chart.addSeries(HistogramSeries, { priceLineVisible: false, priceFormat: fmt }, pane)
        s.macd = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceFormat: fmt }, pane)
        s.macdS = chart.addSeries(LineSeries, { color: '#f97316', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceFormat: fmt }, pane)
      }
      if (p === 'stoch') {
        s.stochK = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1, priceLineVisible: false, priceFormat: PCT }, pane)
        s.stochD = chart.addSeries(LineSeries, { color: '#f97316', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceFormat: PCT }, pane)
        for (const lvl of [80, 20]) s.stochK.createPriceLine({ price: lvl, color: css('--muted'), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false })
      }
      if (p === 'atr') s.atr = chart.addSeries(LineSeries, { color: '#14b8a6', lineWidth: 1, priceLineVisible: false, priceFormat: fmt }, pane)
    })
    // Price pane gets most of the height.
    chart.panes().forEach((pn, i) => pn.setStretchFactor(i === 0 ? 3 : 1))
    mainRef.current = s.main
    seriesRef.current = s

    const onMove = (param: MouseEventParams<Time>) => {
      const d = param.seriesData.get(s.main) as { open?: number; high?: number; low?: number; close?: number; value?: number } | undefined
      if (!d || param.time === undefined) return setLegend(null)
      const close = d.close ?? d.value ?? 0
      setLegend({ time: param.time as number, open: d.open ?? close, high: d.high ?? close, low: d.low ?? close, close, volume: 0 })
    }
    chart.subscribeCrosshairMove(onMove)
    const onRange = (r: LogicalRange | null) => {
      if (r && r.from < 15) needMoreRef.current?.()
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange)
    return () => {
      chart.unsubscribeCrosshairMove(onMove)
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange)
      chart.remove()
      chartRef.current = null
      mainRef.current = null
      seriesRef.current = {}
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, intraday])

  // Push data whenever candles (or the structure) change.
  useEffect(() => {
    const s = seriesRef.current
    if (!s.main || !candles.length) return
    const bars = chartType === 'heikin' ? I.heikinAshi(candles) : candles
    if (chartType === 'line') s.main.setData(candles.map((b) => ({ time: t(b.time), value: b.close })))
    else s.main.setData(bars.map((b) => ({ time: t(b.time), open: b.open, high: b.high, low: b.low, close: b.close })))
    const c = I.close(candles)
    if (s.ema21) s.ema21.setData(line(candles, I.ema(c, 21)))
    if (s.ema50) s.ema50.setData(line(candles, I.ema(c, 50)))
    if (s.ema200) s.ema200.setData(line(candles, I.ema(c, 200)))
    if (s.sma20) s.sma20.setData(line(candles, I.sma(c, 20)))
    if (s.sma50) s.sma50.setData(line(candles, I.sma(c, 50)))
    if (s.vwap) s.vwap.setData(line(candles, I.vwap(candles, intraday)))
    if (s.bbU) {
      const b = I.bollinger(c)
      s.bbU.setData(line(candles, b.upper))
      s.bbL.setData(line(candles, b.lower))
      s.bbM.setData(line(candles, b.mid))
    }
    const up = css('--up')
    const down = css('--down')
    if (s.volume) s.volume.setData(candles.map((b) => ({ time: t(b.time), value: b.volume, color: b.close >= b.open ? up + '99' : down + '99' })))
    if (s.rsi) s.rsi.setData(line(candles, I.rsi(c)))
    if (s.macd) {
      const m = I.macd(c)
      s.macd.setData(line(candles, m.macd))
      s.macdS.setData(line(candles, m.signal))
      s.macdH.setData(candles.map((b, i) => (m.hist[i] === null ? { time: t(b.time) }
        : { time: t(b.time), value: m.hist[i] as number, color: (m.hist[i] as number) >= 0 ? up : down })))
    }
    if (s.stochK) {
      const st = I.stochastic(candles)
      s.stochK.setData(line(candles, st.k))
      s.stochD.setData(line(candles, st.d))
    }
    if (s.atr) s.atr.setData(line(candles, I.atr(candles)))
  }, [candles, config, chartType, intraday])

  const shown = legend ?? candles[candles.length - 1] ?? null
  const chg = shown ? ((shown.close - shown.open) / shown.open) * 100 : 0
  return (
    <div className="relative h-full w-full">
      <div ref={box} className="absolute inset-0" data-testid="price-chart" />
      {shown && (
        <div className="num pointer-events-none absolute left-2 top-1 z-10 flex flex-wrap gap-x-3 text-xs text-muted">
          {(['open', 'high', 'low', 'close'] as const).map((k) => (
            <span key={k}>
              {k[0].toUpperCase()} <span className={shown.close >= shown.open ? 'text-up' : 'text-down'}>{fmtPrice(shown[k], decimals)}</span>
            </span>
          ))}
          <span className={chg >= 0 ? 'text-up' : 'text-down'}>{chg >= 0 ? '+' : ''}{chg.toFixed(2)}%</span>
        </div>
      )}
    </div>
  )
})
