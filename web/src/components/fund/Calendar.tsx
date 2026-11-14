import { useEffect, useRef } from 'react'
import { useNow } from '../TopBar'
import { fmtCountdown } from '../../lib/format'
import { fmtLocalTime, tzLabel, userTimeZone, type CalEvent, type CalendarResponse, type Impact } from '../../lib/fundApi'
import { ErrorBox, Notes, Section, Skeleton, Tip, Toggle } from './Section'

export const CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'CAD', 'NZD', 'CNY', 'INR']
const IMPACTS: { id: Impact; label: string }[] = [
  { id: 'high', label: 'High' },
  { id: 'medium', label: 'Medium' },
  { id: 'low', label: 'Low' },
]
const IMPACT_STYLE: Record<Impact, string> = {
  high: 'bg-down/20 text-down',
  medium: 'bg-wait/20 text-wait',
  low: 'bg-panel-2 text-muted',
  holiday: 'bg-panel-2 text-muted',
}

export interface CalFilters {
  range: 'today' | 'week'
  currency: string // 'pair' | 'all' | 'USD' ...
  impacts: Impact[]
}

/** Banner with a live countdown to the next big event for the selected symbol. */
export function NextEventBanner({ data, loading, error, symbol, onReached }: {
  data?: CalendarResponse
  loading: boolean
  error: unknown
  symbol: string
  onReached?: () => void
}) {
  const now = useNow(1000)
  const ev = data?.next_major
  const secs = ev ? (new Date(ev.time).getTime() - now.getTime()) / 1000 : null
  const fired = useRef<string | null>(null)
  useEffect(() => {
    if (ev && secs !== null && secs <= 0 && fired.current !== ev.time) {
      fired.current = ev.time
      onReached?.()
    }
  }, [ev, secs, onReached])
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-panel-2 px-3 py-2" data-testid="next-event">
      <span className="text-xs uppercase tracking-wide text-muted">Next big event</span>
      {loading ? <span className="text-sm text-muted">Loading…</span>
        : error ? <span className="text-sm text-down">Calendar unavailable</span>
        : !ev ? <span className="text-sm text-muted">No big event for {symbol} in the calendar data available right now.</span>
        : (
          <>
            <span className="text-sm font-semibold">{ev.currency} · {ev.plain_title}</span>
            <span className="text-xs text-muted">({ev.title}) {fmtLocalTime(ev.time, true)} {tzLabel()}{!ev.time_exact && ' (approx. time)'}</span>
            <span className="ml-auto font-mono text-lg font-semibold text-wait" aria-label="countdown">
              {secs !== null && secs > 0 ? `in ${secs > 86400 ? `${Math.floor(secs / 86400)}d ` : ''}${fmtCountdown(secs % 86400)}` : 'now'}
            </span>
            {ev.meaning && <p className="basis-full text-xs text-muted">{ev.meaning}</p>}
          </>
        )}
    </div>
  )
}

function Actual({ e }: { e: CalEvent }) {
  if (!e.actual) {
    return <span className="text-muted" title={e.past ? 'Not in the free calendar feed. US numbers are filled from FRED when FRED_API_KEY is set.' : 'Not released yet'}>–</span>
  }
  const cls = e.surprise === 'higher' ? 'text-up' : e.surprise === 'lower' ? 'text-down' : ''
  return <span className={`font-semibold ${cls}`} title={e.actual_source ? `Source: ${e.actual_source}` : undefined}>{e.actual}</span>
}

export function CalendarSection({ filters, setFilters, data, loading, error, symbol, pairCurrencies }: {
  filters: CalFilters
  setFilters: (f: CalFilters) => void
  data?: CalendarResponse
  loading: boolean
  error: unknown
  symbol: string
  pairCurrencies: string[]
}) {
  const withDay = filters.range === 'week'
  const toggleImpact = (i: Impact) => {
    const has = filters.impacts.includes(i)
    const next = has ? filters.impacts.filter((x) => x !== i) : [...filters.impacts, i]
    setFilters({ ...filters, impacts: next.length ? next : [i] })
  }
  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <Toggle label="Calendar range" value={filters.range} onChange={(range) => setFilters({ ...filters, range })}
        options={[{ id: 'today', label: 'Today' }, { id: 'week', label: 'This week' }]} />
      <select aria-label="Currency" value={filters.currency} onChange={(e) => setFilters({ ...filters, currency: e.target.value })}
        className="rounded border border-line bg-panel-2 px-1 py-0.5 text-xs">
        {pairCurrencies.length > 0 && <option value="pair">{symbol} currencies ({pairCurrencies.join(', ')})</option>}
        <option value="all">All currencies</option>
        {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <div className="inline-flex gap-1" role="group" aria-label="Impact">
        {IMPACTS.map((i) => (
          <button key={i.id} type="button" aria-pressed={filters.impacts.includes(i.id)} onClick={() => toggleImpact(i.id)}
            className={`rounded px-2 py-0.5 text-xs ${filters.impacts.includes(i.id) ? IMPACT_STYLE[i.id] : 'text-muted line-through opacity-60'}`}>
            {i.label}
          </button>
        ))}
      </div>
    </div>
  )
  const events = data?.events ?? []
  return (
    <Section title={<>Economic calendar <span className="font-normal text-muted">· times in your time zone ({userTimeZone()}, {tzLabel()})</span></>}
      right={controls} testId="calendar">
      {loading ? <Skeleton rows={5} /> : error ? <ErrorBox error={error} what="Calendar" /> : events.length === 0 ? (
        <p className="text-sm text-muted">No events match these filters {filters.range === 'today' ? 'today' : 'this week'}.</p>
      ) : (
        <>
          <table className="hidden w-full text-left text-xs md:table">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-2 font-medium">Time</th>
                <th className="pr-2 font-medium">Cur</th>
                <th className="pr-2 font-medium">Event</th>
                <th className="pr-2 font-medium">Impact</th>
                <th className="pr-2 font-medium">Actual<Tip text="The released number. Green = higher than forecast, red = lower." /></th>
                <th className="pr-2 font-medium">Forecast<Tip text="What economists expected." /></th>
                <th className="pr-2 font-medium">Previous</th>
                <th className="font-medium">What it means for {symbol}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={`${e.time}-${e.currency}-${e.title}`} data-testid="cal-row"
                  className={`border-t border-line align-top ${e.past ? 'opacity-50' : ''} ${e.major ? 'bg-wait/10 font-medium' : ''}`}>
                  <td className="whitespace-nowrap py-1 pr-2 font-mono">{fmtLocalTime(e.time, withDay)}{!e.time_exact && <span title="Usual release time, not exact"> ~</span>}</td>
                  <td className="pr-2">{e.currency}</td>
                  <td className="pr-2"><div>{e.plain_title}</div>{e.plain_title !== e.title && <div className="text-[11px] text-muted">{e.title}</div>}</td>
                  <td className="pr-2"><span className={`rounded px-1.5 py-0.5 ${IMPACT_STYLE[e.impact]}`}>{e.impact}</span></td>
                  <td className="pr-2"><Actual e={e} /></td>
                  <td className="pr-2">{e.forecast || '–'}</td>
                  <td className="pr-2">{e.previous || '–'}</td>
                  <td className="text-muted">{e.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="space-y-2 md:hidden">
            {events.map((e) => (
              <li key={`${e.time}-${e.currency}-${e.title}`} className={`rounded border border-line p-2 text-xs ${e.past ? 'opacity-50' : ''} ${e.major ? 'bg-wait/10' : ''}`}>
                <div className="flex items-center gap-2">
                  <span className="font-mono">{fmtLocalTime(e.time, withDay)}</span>
                  <span className="font-semibold">{e.currency}</span>
                  <span className={`rounded px-1.5 ${IMPACT_STYLE[e.impact]}`}>{e.impact}</span>
                </div>
                <div className="mt-1 font-medium">{e.plain_title}</div>
                <div className="text-muted">Actual <Actual e={e} /> · Forecast {e.forecast || '–'} · Previous {e.previous || '–'}</div>
                <div className="mt-1 text-muted">{e.meaning}</div>
              </li>
            ))}
          </ul>
        </>
      )}
      {data && <p className="mt-2 text-[11px] text-muted">Source: {data.source}. Dimmed rows are past events; highlighted rows are big market movers.</p>}
      <Notes notes={data?.notes} />
    </Section>
  )
}
