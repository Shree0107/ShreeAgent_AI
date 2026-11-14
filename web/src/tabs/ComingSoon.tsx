import type { Tab } from '../lib/store'

const INFO: Record<Exclude<Tab, 'chart'>, { title: string; phase: string; text: string }> = {
  plan: { title: 'Trade Plan', phase: 'phase 6',
          text: 'Live BUY / SELL / WAIT cards with entry, stop loss, targets, position size and status. Until then, the daily signal cards are in the classic dashboard (streamlit run ui/app.py → Signals).' },
  fundamentals: { title: 'Fundamentals', phase: 'phase 8',
                  text: 'Economic calendar with countdown, central banks, currency strength meter, news with sentiment, and stock fundamentals.' },
  forecast: { title: 'Forecast', phase: 'phase 9',
              text: 'TimesFM-3 forecasts for 15M / 1H / 4H / Daily with confidence bands, baselines and live accuracy.' },
  performance: { title: 'Performance', phase: 'phase 7',
                 text: 'Backtest results per setup and session, live signal tracking and the comparison between them.' },
}

export default function ComingSoon({ tab }: { tab: Tab }) {
  if (tab === 'chart') return null
  const i = INFO[tab]
  return (
    <div className="mx-auto max-w-xl p-8">
      <h2 className="mb-2 text-xl font-semibold">{i.title}</h2>
      <p className="mb-3 text-muted">{i.text}</p>
      <p className="text-xs text-muted">Arrives in {i.phase} of the platform build.</p>
    </div>
  )
}
