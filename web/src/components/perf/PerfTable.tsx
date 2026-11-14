// Sortable results table: one row per setup x market x session (out-of-sample backtest trades).
import { useState } from 'react'
import { minutesText, num, pct, signed, sortRows, type PerfRow, type SortKey } from '../../lib/perf'

const COLS: { key: SortKey; label: string; title: string }[] = [
  { key: 'setup_name', label: 'Setup', title: 'The kind of trade idea' },
  { key: 'symbol', label: 'Market', title: '' },
  { key: 'session_name', label: 'Session', title: 'Time of day the plan was made' },
  { key: 'trades', label: 'Trades', title: 'Number of test trades' },
  { key: 'win_rate', label: 'Target 1 first', title: 'Share of trades that reached target 1 before the stop loss' },
  { key: 'profit_factor', label: 'Profit factor', title: 'Pips won divided by pips lost. Above 1 = made money; we want at least 1.15' },
  { key: 'expectancy_pips', label: 'Avg per trade', title: 'Average result per trade in pips, after spread and costs' },
  { key: 'max_drawdown_pips', label: 'Worst dip', title: 'Biggest drop of the running total from a high point (max drawdown), in pips' },
  { key: 'median_minutes_to_tp1', label: 'Time to target 1', title: 'Typical time from entry to target 1 (middle half of trades in brackets)' },
]
const TEXT_KEYS: SortKey[] = ['setup_name', 'symbol', 'session_name']

function pfClass(pf: number | null): string {
  if (pf === null) return ''
  if (pf >= 1.15) return 'text-up'
  return pf < 1 ? 'text-down' : ''
}

export function PerfTable({ rows }: { rows: PerfRow[] }) {
  const [key, setKey] = useState<SortKey>('trades')
  const [dir, setDir] = useState<1 | -1>(-1)
  const [bySession, setBySession] = useState(false)
  const shown = sortRows(rows.filter((r) => r.trades > 0 && (bySession ? r.session !== 'all' : r.session === 'all')), key, dir)
  const click = (k: SortKey) => {
    if (k === key) setDir(dir === 1 ? -1 : 1)
    else {
      setKey(k)
      setDir(TEXT_KEYS.includes(k) ? 1 : -1)
    }
  }
  return (
    <div>
      <label className="mb-2 flex items-center gap-2 text-sm text-muted">
        <input type="checkbox" checked={bySession} onChange={(e) => setBySession(e.target.checked)} />
        Split by session (London, New York, …)
      </label>
      {!shown.length ? <p className="text-sm text-muted">No test trades yet.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                {COLS.map((c) => (
                  <th key={c.key} className="px-2 py-1 font-medium" title={c.title}
                    aria-sort={key === c.key ? (dir === 1 ? 'ascending' : 'descending') : 'none'}>
                    <button className="hover:text-fg" onClick={() => click(c.key)}>
                      {c.label}{key === c.key ? (dir === 1 ? ' ▲' : ' ▼') : ''}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.symbol}-${r.setup}-${r.session}`} className="border-b border-line" data-testid="perf-row">
                  <td className="px-2 py-1">{r.setup_name}</td>
                  <td className="px-2 py-1">{r.symbol}</td>
                  <td className="px-2 py-1">{r.session_name}</td>
                  <td className="px-2 py-1 tabular-nums">{r.trades}</td>
                  <td className="px-2 py-1 tabular-nums">{pct(r.win_rate)}</td>
                  <td className={`px-2 py-1 tabular-nums ${pfClass(r.profit_factor)}`}>{num(r.profit_factor, 2)}</td>
                  <td className="px-2 py-1 tabular-nums">{signed(r.expectancy_pips)} pips</td>
                  <td className="px-2 py-1 tabular-nums">{num(r.max_drawdown_pips)} pips</td>
                  <td className="px-2 py-1 tabular-nums">{minutesText(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
