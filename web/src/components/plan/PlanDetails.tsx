import { fmtPrice } from '../../lib/format'
import type { PlanCard } from '../../lib/plans'

const TF_LABEL: Record<string, string> = { '1d': 'Daily', '4h': '4H', '1h': '1H', '15m': '15M', '5m': '5M' }
const DIR_TONE: Record<string, string> = { up: 'text-up', down: 'text-down', neutral: 'text-muted' }

/** The technical breakdown behind a card. Indicator names are allowed here (it's collapsed by default). */
export function PlanDetails({ card }: { card: PlanCard }) {
  const d = card.details ?? {}
  const dec = card.decimals ?? 5
  return (
    <div className="mt-2 space-y-3 rounded border border-line bg-panel-2 p-3 text-xs" data-testid="plan-details">
      {d.mtf && (
        <div>
          <h4 className="mb-1 font-semibold">Timeframes</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-muted"><tr><th className="pr-2">TF</th><th className="pr-2">Direction</th><th className="pr-2">Score</th><th>Why</th></tr></thead>
              <tbody>
                {d.mtf.map((r) => (
                  <tr key={r.tf} className="align-top">
                    <td className="pr-2">{TF_LABEL[r.tf] ?? r.tf}</td>
                    <td className={`pr-2 ${DIR_TONE[r.direction]}`}>{r.direction}</td>
                    <td className="pr-2">{r.score}</td>
                    <td className="text-muted">{(r.details ?? []).join(' · ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {!!d.confirmations?.length && (
        <div>
          <h4 className="mb-1 font-semibold">Confirmations ({d.confirmations.length})</h4>
          <ul className="list-disc pl-4">
            {d.confirmations.map((c) => <li key={c.key}><b>{c.key}</b> {c.tf && `(${c.tf})`}: {c.detail}</li>)}
          </ul>
        </div>
      )}
      {!!d.gates?.length && (
        <div>
          <h4 className="mb-1 font-semibold">Blocking checks</h4>
          <ul className="list-disc pl-4">{d.gates.map((g, i) => <li key={i}><b>{g.code}</b>: {g.text}</li>)}</ul>
        </div>
      )}
      {!!d.candidates?.length && (
        <div>
          <h4 className="mb-1 font-semibold">Setups considered</h4>
          <ul className="list-disc pl-4">
            {d.candidates.map((c, i) => (
              <li key={i}>{c.setup} {c.direction} @ {fmtPrice(c.entry, dec)} · R:R {c.rr1} {c.gates.length ? `· blocked: ${c.gates.join(', ')}` : '· passes'}</li>
            ))}
          </ul>
        </div>
      )}
      {!!d.levels?.length && (
        <div>
          <h4 className="mb-1 font-semibold">Key levels</h4>
          <ul className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            {d.levels.map((l, i) => <li key={i}>{fmtPrice(l.price, dec)} – {l.kind} ({l.label})</li>)}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
        {d.spread && <span>Spread: {d.spread.pips ?? 'n/a'} pips {d.spread.live ? '(live)' : '(typical)'}{d.spread.max ? ` · max ${d.spread.max}` : ''} – {d.spread.note}</span>}
        {d.atr15_pips != null && <span>ATR15: {d.atr15_pips.toFixed(1)} pips</span>}
        {d.market && <span>ADX: {d.market.adx ?? 'n/a'} ({d.market.reason})</span>}
        <span>Raw score: {d.score ?? 0}</span>
      </div>
    </div>
  )
}
