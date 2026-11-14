import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { PriceChart, type PriceChartHandle } from '../components/chart/PriceChart'
import { api } from '../lib/api'
import { decimalsFor } from '../lib/format'
import { INDICATORS, TIMEFRAMES, useApp, type ChartType } from '../lib/store'
import { useCandles } from '../lib/useCandles'

const TYPES: { id: ChartType; label: string }[] = [
  { id: 'candles', label: 'Candles' },
  { id: 'line', label: 'Line' },
  { id: 'heikin', label: 'Heikin Ashi' },
]

function Seg<T extends string>({ items, value, onChange, disabled }: {
  items: { id: T; label: string; title?: string }[]; value: T; onChange: (v: T) => void; disabled?: (v: T) => boolean
}) {
  return (
    <div className="flex overflow-hidden rounded-md border border-line">
      {items.map((it) => (
        <button key={it.id} title={it.title} disabled={disabled?.(it.id)} onClick={() => onChange(it.id)}
          className={`px-2.5 py-1 text-xs font-medium ${value === it.id ? 'bg-accent text-white' : 'text-muted hover:bg-panel-2 hover:text-fg'}`}>
          {it.label}
        </button>
      ))}
    </div>
  )
}

export function ChartTab() {
  const { symbol, tf, setTf, chartType, setChartType, indicators, toggleIndicator, theme } = useApp()
  const { data: supported = ['1h', '4h', '1d', '1wk'] } = useQuery({ queryKey: ['timeframes'], queryFn: api.timeframes, staleTime: Infinity })
  const { data: info } = useQuery({ queryKey: ['symbol', symbol], queryFn: () => api.resolve(symbol), staleTime: Infinity })
  const { candles, source, error, loading, loadMore } = useCandles(symbol, supported.includes(tf) ? tf : '1h')
  const chart = useRef<PriceChartHandle>(null)
  const [menu, setMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  // Close the indicators menu on Escape or a click/tap anywhere outside it (it can cover the chart on phones).
  useEffect(() => {
    if (!menu) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMenu(false)
    const onDown = (e: PointerEvent) => menuRef.current && !menuRef.current.contains(e.target as Node) && setMenu(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [menu])
  const decimals = info?.decimals ?? decimalsFor(symbol, candles.at(-1)?.close)
  const tfSec = TIMEFRAMES.find((x) => x.id === tf)?.seconds ?? 3600

  const screenshot = () => {
    const canvas = chart.current?.screenshot()
    if (!canvas) return
    const a = document.createElement('a')
    a.download = `${symbol.replace('/', '')}_${tf}_${new Date().toISOString().slice(0, 16).replace(':', '')}.png`
    a.href = canvas.toDataURL('image/png')
    a.click()
  }

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Seg items={TIMEFRAMES.map((x) => ({ id: x.id as string, label: x.label,
               title: supported.includes(x.id) ? undefined : 'Needs live intraday data (coming with the OANDA feed)' }))}
             value={tf} onChange={setTf} disabled={(v) => !supported.includes(v)} />
        <Seg items={TYPES} value={chartType} onChange={setChartType} />
        <div className="relative" ref={menuRef}>
          <button onClick={() => setMenu((m) => !m)} aria-expanded={menu}
            className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-muted hover:text-fg">
            ƒx Indicators ({indicators.length})
          </button>
          {menu && (
            <div className="absolute left-0 top-8 z-30 w-48 rounded-md border border-line bg-panel p-1 shadow-xl" role="menu">
              {INDICATORS.map((ind) => (
                <label key={ind.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-panel-2">
                  <input type="checkbox" checked={indicators.includes(ind.id)} onChange={() => toggleIndicator(ind.id)}
                    disabled={(ind.id === 'volume' || ind.id === 'vwap') && info && !info.has_volume} />
                  {ind.label}
                  {(ind.id === 'volume' || ind.id === 'vwap') && info && !info.has_volume && <span className="text-xs text-muted">(no FX volume)</span>}
                </label>
              ))}
              <button onClick={() => setMenu(false)} className="mt-1 w-full rounded bg-panel-2 py-1.5 text-sm font-medium">Done</button>
            </div>
          )}
        </div>
        <button onClick={screenshot} title="Download a PNG of the chart"
          className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-muted hover:text-fg">📷 Screenshot</button>
        <span className="ml-auto text-xs text-muted">
          {loading ? 'Loading…' : `${candles.length} candles · source: ${source || 'n/a'}`}
        </span>
      </div>
      <div className="relative min-h-[420px] flex-1 overflow-hidden rounded-lg border border-line bg-panel">
        {error ? (
          <div className="p-6 text-down">Couldn't load prices for {symbol}: {error}</div>
        ) : (
          <PriceChart ref={chart} candles={candles} chartType={chartType} indicators={indicators} decimals={decimals}
            intraday={tfSec < 86400} hasVolume={info?.has_volume ?? !symbol.includes('/')} theme={theme} onNeedMore={loadMore} />
        )}
      </div>
    </div>
  )
}
