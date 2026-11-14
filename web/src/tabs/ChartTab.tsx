import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { PriceChart, type PriceChartHandle } from '../components/chart/PriceChart'
import { api } from '../lib/api'
import { decimalsFor } from '../lib/format'
import { INDICATORS, TIMEFRAMES, useApp, type ChartType } from '../lib/store'
import { useLiveCandles, useLivePrice } from '../lib/live'
import { fmtCountdown } from '../lib/format'
import { secondsToCandleClose } from '../lib/sessions'
import { useCandles } from '../lib/useCandles'
import { useNow } from '../components/TopBar'
import { useDrawings } from '../components/chart/useDrawings'
import { TOOLS } from '../lib/drawings'
import { DEFAULT_CATEGORIES, OVERLAY_CATEGORIES, overlayShapes, regimeText, type OverlayCategory } from '../lib/overlay'

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
  const activeTf = supported.includes(tf) ? tf : '1h'
  const { candles, source, error, loading, loadMore, applyLive, reload } = useCandles(symbol, activeTf)
  useLiveCandles(symbol, activeTf, applyLive, reload)
  const live = useLivePrice(symbol)
  const now = useNow(1000)
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
  const dr = useDrawings(symbol)
  const [drawMenu, setDrawMenu] = useState(false)
  const toolInfo = TOOLS.find((t) => t.type === dr.tool)
  const [aiOn, setAiOn] = useState(false)
  const [aiMenu, setAiMenu] = useState(false)
  const [cats, setCats] = useState<OverlayCategory[]>(DEFAULT_CATEGORIES)
  const lastBar = candles.at(-1)?.time
  const { data: ov, isFetching: ovLoading, error: ovError } = useQuery({
    queryKey: ['overlay', symbol, activeTf, Math.floor((lastBar ?? 0) / tfSec)],   // refresh once per new candle
    queryFn: async () => {
      const r = await fetch(`/api/overlay?symbol=${encodeURIComponent(symbol)}&tf=${activeTf}`)
      if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText)
      return r.json()
    },
    enabled: aiOn && candles.length > 0, staleTime: 60_000,
  })
  const shapes = useMemo(() => (aiOn ? overlayShapes(ov, cats) : []), [aiOn, ov, cats])
  const drawState = useMemo(() => ({ drawings: dr.drawings, preview: dr.preview, selected: dr.selected }),
                            [dr.drawings, dr.preview, dr.selected])

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
        <div className="relative">
          <button onClick={() => setDrawMenu((m) => !m)} aria-expanded={drawMenu}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium ${dr.tool ? 'border-accent text-accent' : 'border-line text-muted hover:text-fg'}`}>
            ✏ {toolInfo ? toolInfo.label : 'Draw'}
          </button>
          {drawMenu && (
            <div className="absolute left-0 top-8 z-30 w-52 rounded-md border border-line bg-panel p-1 shadow-xl" role="menu">
              {TOOLS.map((t) => (
                <button key={t.type} role="menuitem" onClick={() => { dr.startTool(t.type); setDrawMenu(false) }}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-panel-2">
                  <span className="w-5 text-center text-muted">{t.icon}</span>{t.label}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="relative flex">
          <button onClick={() => setAiOn((v) => !v)} aria-pressed={aiOn}
            title="Draw the system's own trendlines, zones, levels and the current trade plan"
            className={`rounded-l-md border px-2.5 py-1 text-xs font-medium ${aiOn ? 'border-accent bg-accent text-white' : 'border-line text-muted hover:text-fg'}`}>
            ✨ AI analysis{aiOn && ovLoading ? '…' : ''}
          </button>
          <button onClick={() => setAiMenu((m) => !m)} aria-label="Choose what the AI analysis shows" aria-expanded={aiMenu}
            className="rounded-r-md border border-l-0 border-line px-1.5 py-1 text-xs text-muted hover:text-fg">▾</button>
          {aiMenu && (
            <div className="absolute left-0 top-8 z-30 w-72 rounded-md border border-line bg-panel p-1 shadow-xl">
              {OVERLAY_CATEGORIES.map((c) => (
                <label key={c.id} className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-sm hover:bg-panel-2" title={c.help}>
                  <input type="checkbox" className="mt-1" checked={cats.includes(c.id)}
                    onChange={() => setCats((cs) => (cs.includes(c.id) ? cs.filter((x) => x !== c.id) : [...cs, c.id]))} />
                  <span>{c.label}<span className="block text-xs text-muted">{c.help}</span></span>
                </label>
              ))}
              <button onClick={() => setAiMenu(false)} className="mt-1 w-full rounded bg-panel-2 py-1.5 text-sm font-medium">Done</button>
            </div>
          )}
        </div>
        <button onClick={screenshot} title="Download a PNG of the chart"
          className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-muted hover:text-fg">📷 Screenshot</button>
        <span className="ml-auto text-xs text-muted">
          {loading ? 'Loading…' : `${candles.length} candles · ${live.price?.source === 'oanda' ? 'OANDA live' : `source: ${source || 'n/a'}`}`}
          {live.lastUpdate && <> · last update {new Date(live.lastUpdate).toLocaleTimeString()}</>}
          {' · next candle in '}<span className="num">{fmtCountdown(secondsToCandleClose(tfSec, now.getTime() / 1000))}</span>
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 md:flex-row">
        <div className={`relative min-h-[420px] flex-1 overflow-hidden rounded-lg border bg-panel ${dr.tool ? 'border-accent cursor-crosshair' : 'border-line'}`}>
          {aiOn && ov && !toolInfo && (
            <div className="pointer-events-none absolute left-1/2 top-2 z-20 -translate-x-1/2 rounded-md bg-panel-2/90 px-3 py-1 text-xs font-medium shadow" data-testid="regime">
              {regimeText(ov, decimals)}
            </div>
          )}
          {aiOn && ovError && <div className="absolute left-2 top-8 z-20 text-xs text-down">AI analysis unavailable: {(ovError as Error).message}</div>}
          {toolInfo && (
            <div className="absolute left-1/2 top-2 z-20 -translate-x-1/2 rounded-md bg-accent px-3 py-1 text-xs font-medium text-white shadow" role="status">
              {toolInfo.label}: {toolInfo.help} ({dr.pending.length}/{toolInfo.points}) · Esc to cancel
            </div>
          )}
          {error ? (
            <div className="p-6 text-down">Couldn't load prices for {symbol}: {error}</div>
          ) : (
            <PriceChart ref={chart} candles={candles} chartType={chartType} indicators={indicators} decimals={decimals}
              intraday={tfSec < 86400} hasVolume={info?.has_volume ?? !symbol.includes('/')} theme={theme} barSeconds={tfSec}
              onNeedMore={loadMore} draw={drawState} onHover={dr.setHover} overlay={shapes}
              onChartClick={(p) => {
                if (dr.addPoint(p)) return
                dr.setSelected(chart.current?.hitDrawing(p.x, p.y) ?? null)
              }} />
          )}
        </div>
        {(dr.drawings.length > 0 || dr.error) && (
          <aside className="w-full shrink-0 rounded-lg border border-line bg-panel p-2 text-sm md:w-56" aria-label="My drawings">
            <div className="mb-1 flex items-center justify-between">
              <b className="text-xs uppercase tracking-wide text-muted">My drawings ({dr.drawings.length})</b>
              {dr.drawings.length > 0 && <button className="text-xs text-muted hover:text-down" onClick={dr.clearAll}>Clear all</button>}
            </div>
            {dr.error && <div className="mb-1 text-xs text-down">{dr.error}</div>}
            <ul className="space-y-0.5">
              {dr.drawings.map((d) => (
                <li key={d.id} className={`flex items-center gap-1 rounded px-1 ${d.id === dr.selected ? 'bg-panel-2' : ''}`}>
                  <button className="flex-1 truncate py-1 text-left" onClick={() => dr.setSelected(d.id)}>
                    {TOOLS.find((t) => t.type === d.type)?.icon} {d.type === 'text' ? d.text : TOOLS.find((t) => t.type === d.type)?.label}
                    {d.type === 'hline' && <span className="num text-muted"> {d.points[0].price.toFixed(decimals)}</span>}
                  </button>
                  <button title="Delete" aria-label={`Delete ${d.type}`} className="px-1 text-muted hover:text-down" onClick={() => dr.remove(d.id)}>✕</button>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-muted">Click a drawing to select it, Delete to remove. Saved automatically for {symbol}.</p>
          </aside>
        )}
      </div>
    </div>
  )
}
