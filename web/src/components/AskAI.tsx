import { useState } from 'react'
import { useApp } from '../lib/store'

interface Turn {
  role: 'user' | 'assistant'
  content: string
}

/** Side drawer for the existing Claude agent (agent/agent.py via POST /api/agent/ask). */
export function AskAI({ open, onClose }: { open: boolean; onClose: () => void }) {
  const symbol = useApp((s) => s.symbol)
  const [turns, setTurns] = useState<Turn[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [deep, setDeep] = useState(false)

  const ask = async () => {
    const question = q.trim()
    if (!question || busy) return
    const history = turns
    setTurns([...history, { role: 'user', content: question }])
    setQ('')
    setBusy(true)
    try {
      const r = await fetch('/api/agent/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history, deep }),
      })
      const j = await r.json()
      setTurns((t) => [...t, { role: 'assistant', content: r.ok ? j.text || '(empty answer)' : `⚠️ ${j.detail ?? r.statusText}` }])
    } catch (e) {
      setTurns((t) => [...t, { role: 'assistant', content: `⚠️ ${(e as Error).message}` }])
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null
  return (
    <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-line bg-panel shadow-2xl" aria-label="Ask AI">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <b>Ask AI</b>
        <label className="ml-auto flex items-center gap-1 text-xs text-muted" title="Slower, more thorough model">
          <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} /> Deep mode
        </label>
        <button onClick={() => setTurns([])} className="text-xs text-muted hover:text-fg">Clear</button>
        <button onClick={onClose} aria-label="Close" className="px-1 text-lg text-muted hover:text-fg">✕</button>
      </div>
      <div className="flex-1 space-y-3 overflow-auto p-3 text-sm">
        {turns.length === 0 && (
          <p className="text-muted">Ask in plain words, e.g. “Analyse {symbol} for this week” or “Is there a trade on {symbol} today?”.
            Analysis only, not financial advice.</p>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`whitespace-pre-wrap rounded-lg px-3 py-2 ${t.role === 'user' ? 'ml-8 bg-accent/15' : 'mr-4 bg-panel-2'}`}>{t.content}</div>
        ))}
        {busy && <div className="text-muted">Thinking… (the agent runs the analysis tools, this can take a minute)</div>}
      </div>
      <form className="flex gap-2 border-t border-line p-2" onSubmit={(e) => { e.preventDefault(); void ask() }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${symbol}…`}
          className="flex-1 rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent" />
        <button disabled={busy || !q.trim()} className="rounded-md bg-accent px-3 text-sm font-semibold text-white">Send</button>
      </form>
    </aside>
  )
}
