// Simple SVG equity curve (running total of pips over time). Two series: backtest (out-of-sample) and live.
import type { EquityPoint } from '../../lib/perf'

interface Series { label: string; color: string; points: EquityPoint[] }

function lastText(points: EquityPoint[]): string {
  if (!points.length) return 'no trades yet'
  const v = points[points.length - 1].pips
  return `${v > 0 ? '+' : ''}${v.toFixed(1)} pips after ${points.length} trades`
}

export function EquityChart({ series, height = 180 }: { series: Series[]; height?: number }) {
  const all = series.flatMap((s) => s.points)
  if (!all.length) return <p className="text-sm text-muted">No finished trades to draw yet.</p>
  const W = 600
  const H = height
  const pad = 28
  const ts = all.map((p) => Date.parse(p.t))
  const t0 = Math.min(...ts)
  const t1 = Math.max(...ts)
  const vals = [0, ...all.map((p) => p.pips)]
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const x = (t: number) => pad + ((t - t0) / Math.max(1, t1 - t0)) * (W - 2 * pad)
  const y = (v: number) => H - pad - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - 2 * pad)
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img"
        aria-label="Equity curve: running total of pips won or lost">
        <line x1={pad} x2={W - pad} y1={y(0)} y2={y(0)} stroke="var(--border)" strokeDasharray="4 4" />
        <text x={4} y={y(0) - 3} fontSize="10" fill="var(--muted)">0</text>
        <text x={4} y={pad - 10} fontSize="10" fill="var(--muted)">{hi.toFixed(0)} pips</text>
        <text x={4} y={H - 8} fontSize="10" fill="var(--muted)">{lo.toFixed(0)}</text>
        {series.filter((s) => s.points.length).map((s) => {
          const pts = [{ t: s.points[0].t, pips: 0 }, ...s.points]
          const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(Date.parse(p.t)).toFixed(1)},${y(p.pips).toFixed(1)}`).join(' ')
          return <path key={s.label} d={d} fill="none" stroke={s.color} strokeWidth={2} />
        })}
      </svg>
      <figcaption className="flex flex-wrap gap-4 text-xs text-muted">
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-4" style={{ background: s.color }} />
            {s.label}: {lastText(s.points)}
          </span>
        ))}
      </figcaption>
    </figure>
  )
}
