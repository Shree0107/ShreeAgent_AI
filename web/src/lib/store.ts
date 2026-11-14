// App-wide UI state, remembered in localStorage (every access guarded: private windows can block it).
import { create } from 'zustand'

export type Tab = 'chart' | 'plan' | 'fundamentals' | 'forecast' | 'performance'
export type ChartType = 'candles' | 'line' | 'heikin'
export type Theme = 'dark' | 'light'

export const TIMEFRAMES = [
  { id: '1m', label: '1m', seconds: 60 },
  { id: '5m', label: '5m', seconds: 300 },
  { id: '15m', label: '15m', seconds: 900 },
  { id: '1h', label: '1H', seconds: 3600 },
  { id: '4h', label: '4H', seconds: 14400 },
  { id: '1d', label: 'D', seconds: 86400 },
  { id: '1wk', label: 'W', seconds: 604800 },
] as const

export type IndicatorId = 'ema21' | 'ema50' | 'ema200' | 'sma20' | 'sma50' | 'vwap' | 'bb' | 'volume' | 'rsi' | 'macd' | 'stoch' | 'atr'

export const INDICATORS: { id: IndicatorId; label: string; pane: boolean }[] = [
  { id: 'ema21', label: 'EMA 21', pane: false },
  { id: 'ema50', label: 'EMA 50', pane: false },
  { id: 'ema200', label: 'EMA 200', pane: false },
  { id: 'sma20', label: 'SMA 20', pane: false },
  { id: 'sma50', label: 'SMA 50', pane: false },
  { id: 'bb', label: 'Bollinger Bands', pane: false },
  { id: 'vwap', label: 'VWAP', pane: false },
  { id: 'volume', label: 'Volume', pane: true },
  { id: 'rsi', label: 'RSI 14', pane: true },
  { id: 'macd', label: 'MACD', pane: true },
  { id: 'stoch', label: 'Stochastic', pane: true },
  { id: 'atr', label: 'ATR 14', pane: true },
]

interface AppState {
  symbol: string
  tab: Tab
  tf: string
  chartType: ChartType
  indicators: IndicatorId[]
  theme: Theme
  setSymbol: (s: string) => void
  setTab: (t: Tab) => void
  setTf: (t: string) => void
  setChartType: (t: ChartType) => void
  toggleIndicator: (i: IndicatorId) => void
  toggleTheme: () => void
}

const KEY = 'sa-ui'
function load(): Partial<AppState> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}
function save(s: AppState) {
  try {
    const { symbol, tab, tf, chartType, indicators, theme } = s
    localStorage.setItem(KEY, JSON.stringify({ symbol, tab, tf, chartType, indicators, theme }))
    localStorage.setItem('sa-theme', theme)
  } catch {
    /* storage unavailable: settings just won't persist */
  }
}

const saved = load()
export const useApp = create<AppState>((set) => ({
  symbol: saved.symbol ?? 'EUR/USD',
  tab: saved.tab ?? 'chart',
  tf: saved.tf ?? '1h',
  chartType: saved.chartType ?? 'candles',
  indicators: saved.indicators ?? ['ema21', 'ema50', 'volume', 'rsi'],
  theme: saved.theme ?? 'dark',
  setSymbol: (symbol) => set({ symbol }),
  setTab: (tab) => set({ tab }),
  setTf: (tf) => set({ tf }),
  setChartType: (chartType) => set({ chartType }),
  toggleIndicator: (i) => set((s) => ({ indicators: s.indicators.includes(i) ? s.indicators.filter((x) => x !== i) : [...s.indicators, i] })),
  toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
}))

useApp.subscribe((s) => {
  save(s)
  document.documentElement.dataset.theme = s.theme
})
