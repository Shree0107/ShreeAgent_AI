// Performance tab (phase 7): how the intraday setups did in the backtest (out-of-sample), which ones are switched
// off and why, and how your live Trade Plan results compare with what the backtest expected.
// Backtests run on the server in the background ("Run backtest"); this page polls the job's progress.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { EquityChart } from '../components/perf/EquityChart'
import { LivePanel } from '../components/perf/LivePanel'
import { PerfTable } from '../components/perf/PerfTable'
import { perfApi } from '../lib/perf'
import { useApp } from '../lib/store'

function Section({ title, children, testId }: { title: string; children: React.ReactNode; testId?: string }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-3 sm:p-4" data-testid={testId}>
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function RunButton({ symbol, onDone }: { symbol: string; onDone: () => void }) {
  const [starting, setStarting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const status = useQuery({
    queryKey: ['perf-run', symbol],
    queryFn: () => perfApi.status(symbol),
    refetchInterval: (q) => {
      const s = q.state.data?.job?.status
      return s === 'queued' || s === 'running' ? 2000 : false
    },
  })
  const job = status.data?.job
  const running = job?.status === 'queued' || job?.status === 'running'
  const finished = job?.status === 'done' ? job.id : null
  useEffect(() => {
    if (finished) onDone()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished])
  const start = async () => {
    setStarting(true)
    setErr(null)
    try {
      await perfApi.run(symbol)
      await status.refetch()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }
  const p = status.data?.progress
  const share = p && p.total ? Math.round((100 * p.done) / p.total) : null
  return (
    <div className="flex flex-col gap-2 sm:items-end">
      <button onClick={start} disabled={running || starting}
        className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60">
        {running ? 'Backtest running…' : `Run backtest (${symbol})`}
      </button>
      {running && (
        <div className="w-full sm:w-64" role="status">
          <div className="h-1.5 rounded bg-panel-2">
            <div className="h-1.5 rounded bg-accent transition-all" style={{ width: `${share ?? 5}%` }} />
          </div>
          <p className="mt-1 text-xs text-muted">{p?.message || 'Starting…'} This takes a few minutes; you can keep using the app.</p>
        </div>
      )}
      {job?.status === 'error' && <p className="text-xs text-down">The backtest failed: {job.error}</p>}
      {err && <p className="text-xs text-down">Couldn't start the backtest: {err}</p>}
    </div>
  )
}

export default function PerformanceTab() {
  const { symbol } = useApp()
  const qc = useQueryClient()
  const summary = useQuery({ queryKey: ['perf-summary'], queryFn: perfApi.summary })
  const equity = useQuery({ queryKey: ['perf-equity', symbol], queryFn: () => perfApi.equity(symbol) })
  const live = useQuery({ queryKey: ['perf-live'], queryFn: perfApi.liveVsBacktest, refetchInterval: 5 * 60_000 })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['perf-summary'] })
    qc.invalidateQueries({ queryKey: ['perf-equity'] })
    qc.invalidateQueries({ queryKey: ['perf-live'] })
  }
  const s = summary.data
  const run = s?.runs.find((r) => r.symbol === symbol) ?? s?.runs[0]

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-3 p-3 sm:p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold">Performance</h1>
          <p className="text-sm text-muted">
            How each kind of trade idea did when we replayed the Trade Plan engine on past prices (a "backtest"),
            and how your real trades compare.
          </p>
        </div>
        <RunButton symbol={symbol} onDone={refresh} />
      </div>

      {summary.isLoading && <p className="text-muted">Loading…</p>}
      {summary.isError && (
        <p className="rounded border border-down/40 bg-down/10 p-3 text-sm text-down">
          Couldn't load the backtest results: {(summary.error as Error).message}
        </p>
      )}

      {s && !s.has_backtest && (
        <Section title="No backtest yet" testId="empty">
          <p className="text-sm">{s.empty_text}</p>
        </Section>
      )}

      {s && s.has_backtest && (
        <>
          <Section title="In plain words" testId="lines">
            <ul className="space-y-1.5 text-sm">
              {s.lines.map((l) => <li key={l}>{l}</li>)}
            </ul>
            {run && (
              <p className="mt-3 text-xs text-muted">
                {run.method_text} Test period {run.period.start} to {run.period.end}. Made {new Date(run.generated_at).toLocaleString()}.
                {!run.out_of_sample && ' These results are NOT out-of-sample.'}
              </p>
            )}
            {run?.notes.map((n) => <p key={n} className="mt-1 text-xs text-wait">{n}</p>)}
          </Section>

          {s.disabled.length > 0 && (
            <Section title="Switched off for the live Trade Plan" testId="disabled">
              <p className="mb-2 text-xs text-muted">These setups won't give BUY/SELL plans until a new backtest shows they work.</p>
              <ul className="space-y-1 text-sm">
                {s.disabled.map((d) => (
                  <li key={`${d.symbol}-${d.setup}`}><span className="font-medium">{d.setup_name} ({d.symbol}):</span> {d.reason}</li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Results by setup" testId="table">
            <PerfTable rows={s.rows} />
          </Section>
        </>
      )}

      <Section title="Your live results vs the backtest" testId="live">
        {live.isLoading && <p className="text-sm text-muted">Loading…</p>}
        {live.isError && <p className="text-sm text-down">Couldn't load live results.</p>}
        {live.data && <LivePanel data={live.data} />}
      </Section>

      <Section title={`Running total of pips (${symbol})`} testId="equity">
        {equity.isLoading && <p className="text-sm text-muted">Loading…</p>}
        {equity.isError && <p className="text-sm text-down">Couldn't load the equity curve.</p>}
        {equity.data && (
          <EquityChart series={[
            { label: 'Backtest (test period)', color: 'var(--accent)', points: equity.data.backtest[symbol] ?? [] },
            { label: 'Live', color: 'var(--up)', points: equity.data.live },
          ]} />
        )}
        <p className="mt-2 text-xs text-muted">
          Past results don't guarantee future ones. Analysis only – no orders are placed.
        </p>
      </Section>
    </div>
  )
}
