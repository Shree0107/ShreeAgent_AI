import { lazy, Suspense, useEffect, useState } from 'react'
import { AskAI } from './components/AskAI'
import { TopBar } from './components/TopBar'
import { useApp, type Tab } from './lib/store'
import { getSocket } from './lib/ws'
import { ChartTab } from './tabs/ChartTab'

const TABS: { id: Tab; label: string }[] = [
  { id: 'chart', label: 'Chart' },
  { id: 'plan', label: 'Trade Plan' },
  { id: 'fundamentals', label: 'Fundamentals' },
  { id: 'forecast', label: 'Forecast' },
  { id: 'performance', label: 'Performance' },
]

const ComingSoon = lazy(() => import('./tabs/ComingSoon'))
const ForecastTab = lazy(() => import('./tabs/ForecastTab')) // phase 9
const FundamentalsTab = lazy(() => import('./tabs/FundamentalsTab')) // phase 8
const TradePlanTab = lazy(() => import('./tabs/TradePlanTab')) // phase 6
const PerformanceTab = lazy(() => import('./tabs/PerformanceTab')) // phase 7

export default function App() {
  const { tab, setTab } = useApp()
  const [ai, setAi] = useState(false)
  useEffect(() => {
    getSocket() // connect once; components subscribe to topics as they need them
  }, [])
  return (
    <div className="flex h-full flex-col">
      <TopBar onAskAI={() => setAi(true)} />
      <nav className="flex gap-1 overflow-x-auto border-b border-line bg-panel px-2" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg'}`}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="min-h-0 flex-1 overflow-auto">
        {tab === 'chart' ? <ChartTab /> : (
          <Suspense fallback={<div className="p-6 text-muted">Loading…</div>}>
            {tab === 'plan' ? <TradePlanTab /> : tab === 'forecast' ? <ForecastTab /> : tab === 'fundamentals' ? <FundamentalsTab /> : tab === 'performance' ? <PerformanceTab /> /* phase 7 */ : <ComingSoon tab={tab} />}
          </Suspense>
        )}
      </main>
      <footer className="border-t border-line bg-panel px-3 py-1 text-[11px] text-muted">
        Analysis only, not financial advice. No orders are placed. Always use a stop loss.
      </footer>
      <AskAI open={ai} onClose={() => setAi(false)} />
    </div>
  )
}
