import type { ReactNode } from 'react'

/** A card for one tab section. Each section loads and fails on its own. */
export function Section({ title, right, children, className = '', testId }: {
  title: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
  testId?: string
}) {
  return (
    <section className={`min-w-0 rounded-lg border border-line bg-panel p-3 ${className}`} data-testid={testId}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  )
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-2" aria-label="Loading" role="status">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="h-4 rounded bg-panel-2" style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  )
}

export function ErrorBox({ error, what }: { error: unknown; what: string }) {
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div role="alert" className="rounded border border-down/40 bg-down/10 p-2 text-xs text-down">
      {what} unavailable right now. <span className="text-muted">({msg})</span>
    </div>
  )
}

/** Small "?" with a hover / long-press explanation, for anything that needs a word of explanation. */
export function Tip({ text }: { text: string }) {
  return (
    <span title={text} aria-label={text} tabIndex={0}
      className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-line text-[10px] text-muted">
      ?
    </span>
  )
}

export function Notes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null
  return (
    <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
      {notes.map((n) => <li key={n}>ⓘ {n}</li>)}
    </ul>
  )
}

export function Toggle<T extends string>({ value, options, onChange, label }: {
  value: T
  options: { id: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-line" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => onChange(o.id)}
          className={`px-2 py-0.5 text-xs ${value === o.id ? 'bg-accent text-white' : 'text-muted hover:text-fg'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
