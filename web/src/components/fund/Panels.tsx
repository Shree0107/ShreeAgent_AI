// Fundamentals tab sections: bias card, central banks, currency strength, news feed, stock key numbers.
// Each section runs its own query, so one failing source never blanks the whole tab.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { fundApi, fmtLocalTime, type Headline } from '../../lib/fundApi'
import { ErrorBox, Notes, Section, Skeleton, Tip, Toggle } from './Section'

const BIAS_STYLE: Record<string, string> = {
  bullish: 'bg-up/15 text-up border-up/40',
  bearish: 'bg-down/15 text-down border-down/40',
  neutral: 'bg-panel-2 text-muted border-line',
  unknown: 'bg-panel-2 text-muted border-line',
}

export function BiasCard({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ['fund', 'bias', symbol], queryFn: () => fundApi.bias(symbol), staleTime: 10 * 60_000 })
  return (
    <Section title={<>Fundamental bias · {symbol}<Tip text="The slow-moving big picture (interest rates, inflation, growth or company numbers). It is an estimate, not a trade signal." /></>} testId="bias">
      {q.isLoading ? <Skeleton rows={3} /> : q.error ? <ErrorBox error={q.error} what="Fundamental bias" /> : q.data && (
        <div>
          <span className={`inline-block rounded border px-3 py-1 text-lg font-bold ${BIAS_STYLE[q.data.bias] ?? BIAS_STYLE.neutral}`} data-testid="bias-label">
            {q.data.headline}
          </span>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {q.data.why.map((w) => <li key={w}>{w}</li>)}
          </ul>
          <p className="mt-2 text-[11px] text-muted">{q.data.horizon} Source: {q.data.source}.</p>
        </div>
      )}
    </Section>
  )
}

const LEAN_STYLE: Record<string, string> = { cut: 'text-up', hike: 'text-down', hold: 'text-muted', unknown: 'text-muted' }

export function CentralBanks() {
  const q = useQuery({ queryKey: ['fund', 'central-banks'], queryFn: fundApi.centralBanks, staleTime: 60 * 60_000 })
  return (
    <Section title="Central banks (interest rates)" testId="central-banks">
      {q.isLoading ? <Skeleton rows={6} /> : q.error ? <ErrorBox error={q.error} what="Central-bank data" /> : q.data && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-xs">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-2 font-medium">Bank</th>
                  <th className="pr-2 font-medium">Rate<Tip text="The central bank's main interest rate. Higher rates usually make a currency more attractive." /></th>
                  <th className="pr-2 font-medium">Next meeting</th>
                  <th className="font-medium">Where rates may go<Tip text={q.data.tooltip} /></th>
                </tr>
              </thead>
              <tbody>
                {q.data.banks.map((b) => (
                  <tr key={b.currency} className="border-t border-line align-top" data-testid="bank-row">
                    <td className="py-1 pr-2"><span className="font-semibold">{b.short ?? b.currency}</span> <span className="text-muted">{b.currency}</span></td>
                    <td className="pr-2 font-mono">
                      {b.policy_rate != null ? `${b.policy_rate.toFixed(2)}%` : <span className="text-muted" title={b.error ?? 'Needs FRED_API_KEY'}>n/a</span>}
                      {b.rate_as_of && <div className="text-[10px] text-muted">as of {b.rate_as_of}</div>}
                    </td>
                    <td className="pr-2">{b.next_meeting ? b.next_meeting.date : <span className="text-muted">{b.next_meeting_text ?? 'date not in calendar file'}</span>}</td>
                    <td>
                      <span className={`font-medium ${LEAN_STYLE[b.expectation?.lean ?? 'unknown']}`} title={b.expectation?.reasons.join(' ')}>
                        {b.expectation?.label ?? 'not enough data'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Notes notes={q.data.notes} />
        </>
      )}
    </Section>
  )
}

export function StrengthMeter() {
  const [tf, setTf] = useState<'1h' | '4h' | '1d'>('1d')
  const q = useQuery({ queryKey: ['fund', 'strength', tf], queryFn: () => fundApi.strength(tf), refetchInterval: 5 * 60_000 })
  const rows = q.data?.currencies ?? []
  const max = Math.max(0.0001, ...rows.map((r) => Math.abs(r.strength ?? 0)))
  return (
    <Section testId="strength"
      title={<>Currency strength<Tip text="How much each currency rose or fell on average against the 7 others over the chosen time. Right = stronger, left = weaker." /></>}
      right={<Toggle label="Strength timeframe" value={tf} onChange={setTf} options={[{ id: '1h', label: '1H' }, { id: '4h', label: '4H' }, { id: '1d', label: '1D' }]} />}>
      {q.isLoading ? <Skeleton rows={8} /> : q.error ? <ErrorBox error={q.error} what="Currency strength" /> : q.data && (
        <>
          <ul className="space-y-1">
            {rows.map((r) => {
              const w = r.strength == null ? 0 : (Math.abs(r.strength) / max) * 50
              const up = (r.strength ?? 0) >= 0
              return (
                <li key={r.currency} className="flex items-center gap-2 text-xs" data-testid="strength-row">
                  <span className="w-9 font-semibold">{r.currency}</span>
                  <div className="relative h-3 flex-1 rounded bg-panel-2" title={`${r.name}: average move ${r.strength?.toFixed(2) ?? 'n/a'}% over ${r.n_pairs} pairs`}>
                    <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
                    {r.strength != null && (
                      <div className={`absolute inset-y-0 rounded ${up ? 'bg-up' : 'bg-down'}`}
                        style={up ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
                    )}
                  </div>
                  <span className={`w-14 text-right font-mono ${r.strength == null ? 'text-muted' : up ? 'text-up' : 'text-down'}`}>
                    {r.strength == null ? 'no data' : `${r.strength >= 0 ? '+' : ''}${r.strength.toFixed(2)}%`}
                  </span>
                </li>
              )
            })}
          </ul>
          <p className="mt-2 text-[11px] text-muted">
            {q.data.as_of ? `Prices up to ${fmtLocalTime(q.data.as_of, true)}` : 'No prices'} · source {q.data.sources.join(', ') || 'n/a'}
            {q.data.live ? ' (live)' : ' (delayed, not live)'}
          </p>
          <Notes notes={q.data.notes} />
        </>
      )}
    </Section>
  )
}

const DOT: Record<Headline['label'], string> = { positive: 'bg-up', negative: 'bg-down', neutral: 'bg-muted' }

export function NewsFeed({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ['fund', 'news', symbol], queryFn: () => fundApi.news(symbol), staleTime: 15 * 60_000 })
  const s = useQuery({ queryKey: ['fund', 'news-summary', symbol], queryFn: () => fundApi.newsSummary(symbol),
    staleTime: 60 * 60_000, enabled: !!q.data?.headlines.length })
  const sums = new Map((s.data?.items ?? []).map((i) => [i.title, i.summary]))
  return (
    <Section testId="news"
      title={<>News · {symbol}<Tip text="Dots show the tone of each headline: green positive, red negative, grey neutral. Worked out automatically, so it can be wrong." /></>}>
      {q.isLoading ? <Skeleton rows={5} /> : q.error ? <ErrorBox error={q.error} what="News" /> : !q.data?.headlines.length ? (
        <p className="text-sm text-muted">No recent headlines for {symbol}.</p>
      ) : (
        <>
          <ul className="space-y-2">
            {q.data.headlines.map((h) => (
              <li key={h.url + h.title} className="flex gap-2 text-sm" data-testid="news-item">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[h.label]}`} aria-label={`${h.label} news`} title={`${h.label} (${h.sentiment})`} />
                <div className="min-w-0">
                  <a href={h.url} target="_blank" rel="noreferrer" className="hover:underline">{h.title}</a>
                  <div className="text-[11px] text-muted">{h.source} · {h.date}</div>
                  {sums.get(h.title) && <div className="text-xs text-muted">AI: {sums.get(h.title)}</div>}
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-muted">
            Overall tone: {q.data.label} ({q.data.n_articles} articles, method {q.data.method}).{' '}
            {s.isLoading ? 'Loading AI summaries…' : s.error ? 'AI summaries unavailable.' : s.data?.note}
          </p>
        </>
      )}
    </Section>
  )
}

const TONE: Record<string, string> = { good: 'text-up', bad: 'text-down', neutral: 'text-fg' }

export function StockNumbers({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ['fund', 'stock', symbol], queryFn: () => fundApi.stock(symbol), staleTime: 60 * 60_000 })
  return (
    <Section title={<>Company numbers · {q.data?.name ?? symbol}</>} testId="stock">
      {q.isLoading ? <Skeleton rows={6} /> : q.error ? <ErrorBox error={q.error} what="Company numbers" /> : q.data && (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            {q.data.facts.map((f) => (
              <div key={f.key} className="rounded border border-line bg-panel-2 p-2" data-testid="fact">
                <div className="flex items-baseline justify-between text-xs text-muted">
                  <span>{f.label}{f.tip && <Tip text={f.tip} />}</span>
                  <span className={`font-mono text-sm font-semibold ${TONE[f.tone]}`}>{f.value}</span>
                </div>
                <p className="mt-1 text-sm">{f.text}</p>
              </div>
            ))}
          </div>
          {q.data.facts.length === 0 && <p className="text-sm text-muted">No company figures available.</p>}
          {q.data.earnings && <p className="mt-2 text-sm">📅 {q.data.earnings.text}</p>}
          {q.data.analysts && <p className="mt-1 text-sm">🧑‍💼 {q.data.analysts.text}</p>}
          <p className="mt-2 text-[11px] text-muted">Source: {q.data.source} (updated daily, not live).</p>
        </>
      )}
    </Section>
  )
}
