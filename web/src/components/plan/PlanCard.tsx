import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api } from '../../lib/api'
import { fmtCountdown, fmtPrice } from '../../lib/format'
import {
  TIMELINE, decisionOf, liveDistances, planShapes, staleness, timelineStep, type PlanCard as Card,
} from '../../lib/plans'
import { secondsToCandleClose } from '../../lib/sessions'
import { useApp } from '../../lib/store'
import { PriceChart } from '../chart/PriceChart'
import { PlanDetails } from './PlanDetails'
import { Term } from './Term'

const TONE = {
  up: 'bg-up text-white', down: 'bg-down text-white', wait: 'bg-wait text-black', ready: 'bg-ready text-black',
} as const

const MARKET_TONE: Record<string, string> = { trending_up: 'text-up', trending_down: 'text-down', sideways: 'text-wait' }

export const DISCLAIMER = 'Analysis only, not financial advice. Always use a stop loss.'

function Row({ label, children, term }: { label: string; children: ReactNode; term?: string }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-2 py-0.5 text-sm">
      <div className="font-semibold text-muted">{term ? <Term word={term}>{label}</Term> : label}</div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function Timeline({ card }: { card: Card }) {
  const { step, result } = timelineStep(card.state, !!card.closed)
  const bad = ['sl_hit', 'cancelled', 'expired'].includes(card.state)
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label="Status">
      {TIMELINE.map((t, i) => {
        const label = i === 4 && result ? result : t.label
        const active = i === step
        const done = i < step
        return (
          <li key={t.id} className="flex items-center gap-1">
            <span aria-current={active ? 'step' : undefined}
              className={`rounded px-1.5 py-0.5 ${active ? (i === 4 && bad ? 'bg-down text-white' : i === 4 ? 'bg-up text-white' : 'bg-accent text-white')
                : done ? 'text-fg' : 'text-muted'}`}>
              {label}
            </span>
            {i < TIMELINE.length - 1 && <span className="text-muted">→</span>}
          </li>
        )
      })}
    </ol>
  )
}

export function MiniChart({ card }: { card: Card }) {
  const theme = useApp((s) => s.theme)
  const { data } = useQuery({
    queryKey: ['candles', card.symbol, '15m', 120],
    queryFn: () => api.candles(card.symbol, '15m', 120),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
  if (!data?.candles.length) return <div className="h-44 rounded bg-panel-2" aria-label="Chart loading" />
  return (
    <div className="h-44 overflow-hidden rounded border border-line">
      <PriceChart candles={data.candles} chartType="candles" indicators={[]} decimals={card.decimals ?? 5} intraday
        hasVolume={false} theme={theme} barSeconds={900} overlay={planShapes(card)} />
    </div>
  )
}

interface Props {
  card: Card
  price?: number | null       // live mid price (WebSocket)
  feed?: string               // live feed status: live | delayed | stale | closed | error
  now?: number                // ms, for tests
  chart?: boolean
}

export function PlanCard({ card, price, feed, now = Date.now(), chart = true }: Props) {
  const [open, setOpen] = useState(false)
  const ex = card.explanation
  const g = ex.glossary
  const dec = card.decimals ?? 5
  const d = decisionOf(card)
  const st = staleness(card, now, feed)
  const livePx = price ?? card.price
  const dist = liveDistances(card, price ?? null)
  const trade = card.action !== 'WAIT'
  const updated = new Date(card.generated_at).toLocaleTimeString('en-GB', { hour12: false })
  const next = fmtCountdown(secondsToCandleClose(900, now / 1000))
  const size = card.size

  return (
    <article data-testid="plan-card" aria-label={`${card.symbol} ${d.label}`}
      className={`rounded-lg border border-line bg-panel p-3 sm:p-4 ${st.stale ? 'opacity-60 grayscale' : ''}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h3 className="text-lg font-semibold">{card.symbol}</h3>
          <span className="tabular-nums">{fmtPrice(livePx, dec)}</span>
          {card.market_text && <span className={`text-sm ${MARKET_TONE[card.market]}`}>
            {card.market === 'sideways' ? <Term word="Sideways" glossary={g}>Sideways</Term> : card.market_text}</span>}
          {card.session_label && <span className="text-xs text-muted">· {card.session_label}</span>}
        </div>
        <div className="text-xs text-muted">Last updated {updated} · next candle {next}</div>
      </header>

      {st.stale && <div role="status" className="mt-1 rounded bg-panel-2 px-2 py-1 text-xs font-medium text-wait">{st.label}</div>}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span data-testid="decision" className={`rounded px-3 py-1 text-base font-bold tracking-wide ${TONE[d.tone]}`}>{d.label}</span>
        {trade && <span className="text-sm"><Term word="Confidence" glossary={g}>{ex.confidence_text ?? card.confidence}</Term></span>}
        {ex.probability_text && <span className="text-sm text-muted">· {ex.probability_text}</span>}
      </div>

      {card.state !== 'pending' && <div className="mt-2"><Timeline card={card} /></div>}

      <p className="mt-2 font-medium">{ex.headline}</p>
      {!!ex.why?.length && (
        <div className="mt-1">
          <h4 className="text-xs font-semibold uppercase text-muted">Why?</h4>
          <ul className="list-disc pl-5 text-sm">{ex.why.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      {!trade && (
        <div className="mt-2 space-y-1 text-sm">
          {!!ex.waiting_for?.length && (<>
            <h4 className="text-xs font-semibold uppercase text-muted">What I'm waiting for</h4>
            <ul className="list-disc pl-5">{ex.waiting_for.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </>)}
          {!!card.scenarios?.length && (
            <div className="grid gap-2 sm:grid-cols-2" data-testid="scenarios">
              {card.scenarios.map((s) => (
                <div key={s.direction} className={`rounded border border-line p-2 ${s.direction === 'long' ? 'text-up' : 'text-down'}`}>
                  <div className="font-semibold">{s.text}</div>
                  <div className="text-xs text-muted">{s.likely_pct}% likely{s.why ? ` – ${s.why}` : ''}</div>
                </div>
              ))}
            </div>
          )}
          {ex.closest_idea && <p className="text-xs text-muted">{ex.closest_idea}</p>}
          {ex.time_window_text && !!card.scenarios?.length && <p className="text-xs text-muted">A breakout is {ex.time_window_text}.</p>}
        </div>
      )}

      {trade && (
        <div className="mt-2 divide-y divide-line/50">
          <Row label="Entry">
            <span className="font-semibold">{ex.entry_text}</span>{' '}
            <span className="text-muted">(<Term word={card.entry_type === 'stop' ? 'Stop order' : 'Limit order'} glossary={g}>{ex.order_text}</Term>)</span>
            {dist.entry && <span className="ml-1 text-ready" data-testid="dist-entry"> · {dist.entry} away</span>}
          </Row>
          <Row label="Stop loss" term="Stop loss">
            {ex.stop_text}{ex.stop_money && <span className="text-down"> · {ex.stop_money}</span>}
            {ex.stop_reason && <div className="text-xs text-muted">{ex.stop_reason}</div>}
          </Row>
          {ex.targets.map((t, i) => (
            <Row key={t.label} label={t.label} term="Target">
              <span className="text-up">{t.text}</span>
              {(i === 0 ? ex.tp1_money : ex.tp2_money) && <span className="text-up"> · {i === 0 ? ex.tp1_money : ex.tp2_money}</span>}
            </Row>
          ))}
          <Row label="Reward" term="Risk vs reward">{ex.rr_money_text ?? ex.rr_text}</Row>
          <Row label="Size" term="Lot">
            {size ? <><b>{ex.size_text}</b> <span className="text-xs text-muted">{ex.size_note}</span></> : <span className="text-muted">{ex.size_note || 'Enter your account size above'}</span>}
          </Row>
          <Row label="Break-even" term="Break-even">{ex.breakeven_text}</Row>
          <Row label="Close by" term="Time stop">{ex.time_stop_text}</Row>
          <Row label="Cancel if"><ul className="list-disc pl-4">{ex.cancel.map((c, i) => <li key={i}>{c}</li>)}</ul></Row>
          {ex.time_window_text && <Row label="When">{ex.time_window_text}</Row>}
        </div>
      )}

      {dist.sentence && <p className="mt-2 text-sm font-medium text-ready" data-testid="live-distance">{dist.sentence}</p>}
      {ex.news_warning && <p className="mt-2 rounded bg-panel-2 px-2 py-1 text-sm text-wait">⚠ {ex.news_warning}</p>}

      {chart && card.state !== 'pending' && <div className="mt-3"><MiniChart card={card} /></div>}

      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="mt-2 text-sm text-accent hover:underline">{open ? '▾ Hide details' : '▸ Show details'}</button>
      {open && <PlanDetails card={card} />}

      <p className="mt-2 text-[11px] text-muted">{ex.disclaimer || DISCLAIMER}</p>
    </article>
  )
}
