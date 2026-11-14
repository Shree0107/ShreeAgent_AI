import { useEffect, useRef, useState } from 'react'
import { getSocket } from '../lib/ws'

export interface AlertMsg {
  title: string
  body: string
  type: string
  symbol?: string
  ts: number
}

const canNotify = () => typeof window !== 'undefined' && 'Notification' in window

/** Bell in the top bar: trade-plan alerts as desktop notifications (when allowed) plus an in-app list. */
export function AlertsBell() {
  const [items, setItems] = useState<AlertMsg[]>([])
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [perm, setPerm] = useState<string>(canNotify() ? Notification.permission : 'unsupported')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => getSocket().on('alert', (d) => {
    const a = d as AlertMsg
    setItems((xs) => [a, ...xs].slice(0, 30))
    setUnread((n) => n + 1)
    if (canNotify() && Notification.permission === 'granted') {
      try {
        new Notification(a.title, { body: a.body, tag: `${a.symbol}-${a.type}` })
      } catch {
        /* some browsers only allow notifications from a service worker: the in-app list still works */
      }
    }
  }), [])

  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const enable = async () => {
    if (!canNotify()) return
    setPerm(await Notification.requestPermission())
  }

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => { setOpen((o) => !o); setUnread(0) }} aria-label={`Alerts${unread ? ` (${unread} new)` : ''}`}
        className="relative rounded-md border border-line px-2 py-1 text-sm" title="Trade alerts">
        🔔{unread > 0 && <span className="absolute -right-1.5 -top-1.5 rounded-full bg-down px-1 text-[10px] font-bold text-white">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 rounded-md border border-line bg-panel p-2 shadow-xl">
          <div className="mb-1 flex items-center justify-between">
            <b className="text-sm">Alerts</b>
            {perm === 'default' && <button onClick={enable} className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-white">Enable desktop alerts</button>}
            {perm === 'granted' && <span className="text-xs text-up">Desktop alerts on</span>}
            {perm === 'denied' && <span className="text-xs text-muted" title="Allow notifications for this site in your browser settings">Blocked in browser</span>}
          </div>
          {items.length === 0 ? (
            <p className="py-3 text-xs text-muted">No alerts yet. You'll be alerted when a setup is getting ready, when an entry triggers, and when a target or stop is hit. Telegram alerts: see SETUP.md.</p>
          ) : (
            <ul className="max-h-80 space-y-1 overflow-auto">
              {items.map((a, i) => (
                <li key={i} className="rounded bg-panel-2 px-2 py-1.5 text-xs">
                  <div className="font-semibold">{a.title}</div>
                  <div className="whitespace-pre-line text-muted">{a.body}</div>
                  <div className="text-[10px] text-muted">{new Date(a.ts * 1000).toLocaleTimeString()}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
