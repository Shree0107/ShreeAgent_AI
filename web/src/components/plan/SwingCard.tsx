import type { SwingCard as Card } from '../../lib/plans'
import { DISCLAIMER } from './PlanCard'

const TONE: Record<string, string> = { BUY: 'bg-up text-white', SELL: 'bg-down text-white', WAIT: 'bg-wait text-black' }

/** Daily swing card from the existing /api/signals engine (signals/), shown in "Swing (daily)" mode. */
export function SwingCard({ card }: { card: Card }) {
  const ex = card.explanation
  if (!ex) {
    return (
      <article data-testid="swing-card" className="rounded-lg border border-line bg-panel p-3 opacity-70">
        <h3 className="font-semibold">{card.symbol}</h3>
        <p className="text-sm text-muted">{card.message ?? card.error ?? 'Analysing…'}</p>
      </article>
    )
  }
  const trade = card.action === 'BUY' || card.action === 'SELL'
  return (
    <article data-testid="swing-card" className={`rounded-lg border border-line bg-panel p-3 sm:p-4 ${card.stale ? 'opacity-60' : ''}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-semibold">{card.symbol} <span className="text-sm font-normal text-muted">{card.price_text}</span></h3>
        {card.generated_at && <span className="text-xs text-muted">Updated {new Date(card.generated_at).toLocaleString('en-GB')}{card.stale ? ' · updating…' : ''}</span>}
      </header>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className={`rounded px-3 py-1 font-bold ${TONE[card.action] ?? 'bg-panel-2'}`}>{card.action}</span>
        <span className="text-sm text-muted">{ex.confidence_text}</span>
      </div>
      <ul className="mt-2 list-disc pl-5 text-sm">{ex.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      {trade ? (
        <div className="mt-2 space-y-0.5 text-sm">
          <div><b>Entry</b> {ex.entry_text}</div>
          <div><b>Stop loss</b> {ex.stop_text} <span className="text-muted">– {ex.stop_why}</span></div>
          {ex.targets.map((t) => <div key={t.label}><b>{t.label}</b> <span className="text-up">{t.price_text} ({t.distance}){t.money ? ` · ${t.money}` : ''}</span></div>)}
          {ex.rr_text && <div>{ex.rr_text}</div>}
          {ex.size_text && <div><b>Size</b> {ex.size_text}</div>}
          {!!ex.cancel.length && <div><b>Cancel if</b> {ex.cancel.join(' ')}</div>}
        </div>
      ) : (
        !!ex.waiting_for.length && <ul className="mt-2 list-disc pl-5 text-sm text-muted">{ex.waiting_for.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}
      {ex.event_warning && <p className="mt-2 text-sm text-wait">⚠ {ex.event_warning}</p>}
      <p className="mt-2 text-[11px] text-muted">{DISCLAIMER}</p>
    </article>
  )
}
