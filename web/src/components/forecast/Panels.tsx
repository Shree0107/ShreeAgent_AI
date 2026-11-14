// Plain-language blocks of the Forecast tab. Technical numbers sit behind "Show details".
import { fmtPrice } from '../../lib/format'
import { fmtTime, type Accuracy, type Agreement, type ForecastCheck, type LiveForecast } from '../../lib/forecast'

export function Card({ title, children, testId }: { title: string; children: React.ReactNode; testId?: string }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-3" data-testid={testId}>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  )
}

const VERDICT_TONE: Record<ForecastCheck['status'], string> = {
  better: 'text-up', same: 'text-wait', worse: 'text-down', unknown: 'text-muted',
}
const VERDICT_LABEL: Record<ForecastCheck['status'], string> = {
  better: 'Beats simple guesses', same: 'No better than simple guesses', worse: 'Worse than simple guesses',
  unknown: 'Not checked yet',
}

export function VerdictCard({ check, variatesText, details }: { check: ForecastCheck | null; variatesText?: string; details: boolean }) {
  const c = check ?? { status: 'unknown' as const, text: 'The model has not been checked on past data yet. Treat the forecast as a rough guide.', table: [], run_at: null }
  return (
    <Card title="Is the model any good here?" testId="verdict">
      <p className={`mb-1 text-sm font-semibold ${VERDICT_TONE[c.status]}`}>{VERDICT_LABEL[c.status]}</p>
      <p className="text-sm">{c.text}</p>
      {variatesText && <p className="mt-1 text-xs text-muted">{variatesText}</p>}
      {details && c.table.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs" aria-label="Model vs simple baselines">
            <thead className="text-muted">
              <tr><th className="text-left font-normal">Method</th>
                <th className="text-right font-normal">Typical error ({c.units})</th>
                <th className="text-right font-normal">Direction right</th></tr>
            </thead>
            <tbody>
              {c.table.map((r) => (
                <tr key={r.name} className={r.name === 'model' ? 'font-semibold' : ''}>
                  <td>{r.label}</td>
                  <td className="text-right tabular-nums">{r.error ?? '–'}</td>
                  <td className="text-right tabular-nums">{r.direction_pct === null ? '–' : `${r.direction_pct}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-muted">
            {c.n_windows} past test windows · inside middle range {c.coverage_50 ?? '–'}% (ideal 50%) · inside wide range {c.coverage_80 ?? '–'}% (ideal 80%)
            {c.multivariate?.tested && ` · own prices only: ${c.multivariate.error_own_prices} vs with ${(c.multivariate.variates_tested ?? []).filter((v) => v !== 'close').join(', ') || 'volume'}: ${c.multivariate.error_with_extras}`}
            {c.run_at && ` · checked ${fmtTime(c.run_at)}`}
          </p>
        </div>
      )}
    </Card>
  )
}

const ARROW = { up: '↑', down: '↓', flat: '→' } as const

export function AccuracyCard({ acc, decimals, details }: { acc: Accuracy | undefined; decimals: number; details: boolean }) {
  if (!acc) return <Card title="How past forecasts turned out" testId="accuracy"><p className="text-sm text-muted">Loading…</p></Card>
  const recent = acc.recent ?? []
  const rows = details ? recent : recent.slice(0, 5)
  return (
    <Card title="How past forecasts turned out" testId="accuracy">
      <p className="text-sm">{acc.text}</p>
      {rows.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs" aria-label="Past forecasts vs what happened">
            <thead className="text-muted">
              <tr><th className="text-left font-normal">Made</th><th className="text-right font-normal">Forecast</th>
                <th className="text-right font-normal">Actual</th><th className="text-right font-normal">Direction</th>
                {details && <th className="text-right font-normal">Error ({acc.units})</th>}</tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.last_bar_time}>
                  <td>{fmtTime(r.made_at)}</td>
                  <td className="text-right tabular-nums">{ARROW[r.predicted_dir]} {fmtPrice(r.predicted_end, decimals)}</td>
                  <td className="text-right tabular-nums">{ARROW[r.actual_dir]} {fmtPrice(r.actual_end, decimals)}</td>
                  <td className={`text-right ${r.dir_correct === null ? 'text-muted' : r.dir_correct ? 'text-up' : 'text-down'}`}>
                    {r.dir_correct === null ? 'no call' : r.dir_correct ? 'right' : 'wrong'}
                  </td>
                  {details && <td className="text-right tabular-nums">{r.error ?? '–'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

const AGREE_TONE: Record<Agreement['status'], string> = {
  agree: 'text-up', disagree: 'text-down', neutral: 'text-wait', none: 'text-muted',
}

export function AgreementCard({ ag, outdated }: { ag: Agreement | undefined; outdated: boolean }) {
  return (
    <Card title="Forecast vs trade plan" testId="agreement">
      {!ag ? <p className="text-sm text-muted">Checking the plan…</p> : (
        <>
          <p className={`text-sm font-medium ${AGREE_TONE[ag.status]}`}>{ag.text}</p>
          {ag.plan && (
            <p className="mt-1 text-xs text-muted">
              Compared with the {ag.plan.source === 'intraday' ? 'intraday trade plan' : 'daily signal'} ({ag.plan.action})
              {ag.plan.generated_at ? `, made ${fmtTime(ag.plan.generated_at)}` : ''}.
              {outdated && ' The forecast is out of date, so this comparison may be too.'}
            </p>
          )}
        </>
      )}
    </Card>
  )
}

export function SummaryCard({ d, outdated }: { d: LiveForecast; outdated: boolean }) {
  const f = d.forecast
  if (!f) return null
  const tone = f.direction === 'up' ? 'text-up' : f.direction === 'down' ? 'text-down' : 'text-muted'
  return (
    <Card title={`Next ${d.horizon_text}`} testId="summary">
      <p className={`text-base ${outdated ? 'text-muted' : ''}`}>
        <span className={`mr-1 font-semibold ${tone}`}>{ARROW[f.direction]}</span>{f.summary}
      </p>
      {outdated && (
        <p className="mt-1 text-xs text-wait" role="status">
          Out of date: it is based on older candles. Don't act on it until it has updated.
        </p>
      )}
    </Card>
  )
}
