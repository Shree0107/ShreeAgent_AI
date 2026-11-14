// Live tracking: your real Trade Plan results compared with the range the backtest expected.
import { num, pct, signed, type Comparison, type LiveVsBacktest } from '../../lib/perf'

const STATUS: Record<Comparison['status'], { label: string; cls: string }> = {
  inside: { label: 'As expected', cls: 'bg-up/15 text-up' },
  below: { label: 'Worse than expected', cls: 'bg-down/15 text-down' },
  above: { label: 'Better than expected', cls: 'bg-ready/15 text-ready' },
  no_live: { label: 'No live trades yet', cls: 'bg-panel-2 text-muted' },
  no_backtest: { label: 'No backtest yet', cls: 'bg-panel-2 text-muted' },
}

function Band({ c }: { c: Comparison }) {
  if (!c.band || c.live.win_rate === null) return null
  const w = (v: number) => Math.max(0, Math.min(100, v * 100))
  return (
    <div className="mt-2" data-testid="band">
      <div className="relative h-3 rounded bg-panel-2">
        <div className="absolute h-3 rounded bg-accent/30" style={{ left: `${w(c.band.low)}%`, width: `${w(c.band.high) - w(c.band.low)}%` }} />
        <div className="absolute -top-0.5 h-4 w-1 rounded bg-fg" style={{ left: `${w(c.live.win_rate)}%` }} title="Your live result" />
      </div>
      <div className="mt-1 flex justify-between gap-2 text-[11px] text-muted">
        <span>0%</span><span className="text-center">shaded = what the backtest expected (9 times out of 10); line = you</span><span>100%</span>
      </div>
    </div>
  )
}

export function LivePanel({ data }: { data: LiveVsBacktest }) {
  const o = data.overall
  const s = STATUS[o.status]
  return (
    <div data-testid="live-panel">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold ${s.cls}`}>{s.label}</span>
        <p className="text-sm">{o.sentence}</p>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted">Live trades</dt><dd className="tabular-nums">{o.live.trades}</dd></div>
        <div>
          <dt className="text-xs text-muted" title="Share of trades that reached target 1">Reached target 1</dt>
          <dd className="tabular-nums">{pct(o.live.win_rate)} <span className="text-xs text-muted">(backtest {pct(o.backtest.win_rate)})</span></dd>
        </div>
        <div>
          <dt className="text-xs text-muted" title="Pips won divided by pips lost. Above 1 = made money">Profit factor</dt>
          <dd className="tabular-nums">{num(o.live.profit_factor, 2)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Average per trade</dt>
          <dd className="tabular-nums">{signed(o.live.avg_pips)} pips <span className="text-xs text-muted">(backtest {signed(o.backtest.avg_pips)})</span></dd>
        </div>
      </dl>
      <Band c={o} />
      {data.rows.some((r) => r.live.trades > 0) && (
        <ul className="mt-3 space-y-1 text-sm">
          {data.rows.filter((r) => r.live.trades > 0).map((r) => (
            <li key={`${r.symbol}-${r.setup}`}><span className="font-medium">{r.setup_name} ({r.symbol}):</span> {r.sentence}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
