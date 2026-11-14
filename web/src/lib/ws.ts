// WebSocket client for /ws with automatic reconnect (exponential backoff + jitter) and a heartbeat
// watchdog: if nothing arrives for 2.5x the server heartbeat, the connection is treated as dead.

import { create } from 'zustand'

export type ConnState = 'connecting' | 'live' | 'reconnecting' | 'offline'

interface ConnStore {
  state: ConnState
  lastMessage: number | null
  attempts: number
  set: (p: Partial<ConnStore>) => void
}

export const useConnection = create<ConnStore>((set) => ({
  state: 'connecting',
  lastMessage: null,
  attempts: 0,
  set: (p) => set(p),
}))

type Handler = (data: unknown, topic: string) => void

export function backoffMs(attempt: number, base = 500, max = 15_000, random = Math.random): number {
  const exp = Math.min(max, base * 2 ** attempt)
  return Math.round(exp / 2 + (random() * exp) / 2) // "equal jitter"
}

export class LiveSocket {
  private ws: WebSocket | null = null
  private handlers = new Map<string, Set<Handler>>()
  private attempt = 0
  private heartbeatMs = 15_000
  private watchdog: ReturnType<typeof setTimeout> | null = null
  private retry: ReturnType<typeof setTimeout> | null = null
  private closed = false
  private url: string

  constructor(url?: string) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.url = url ?? `${proto}://${location.host}/ws`
  }

  connect(): void {
    this.closed = false
    useConnection.getState().set({ state: this.attempt ? 'reconnecting' : 'connecting', attempts: this.attempt })
    const ws = new WebSocket(this.url)
    this.ws = ws
    ws.onopen = () => {
      this.attempt = 0
      useConnection.getState().set({ state: 'live', attempts: 0 })
      this.send({ op: 'subscribe', topics: [...this.handlers.keys()] })
      this.kick()
    }
    ws.onmessage = (ev) => {
      this.kick()
      useConnection.getState().set({ lastMessage: Date.now() })
      let msg: { topic: string; data: unknown }
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      if (msg.topic === 'hello' && typeof (msg.data as { heartbeat_s?: number }).heartbeat_s === 'number') {
        this.heartbeatMs = (msg.data as { heartbeat_s: number }).heartbeat_s * 1000
      }
      for (const [pattern, hs] of this.handlers) {
        if (pattern === msg.topic || (pattern.endsWith('*') && msg.topic.startsWith(pattern.slice(0, -1)))) {
          hs.forEach((h) => h(msg.data, msg.topic))
        }
      }
    }
    ws.onclose = () => this.scheduleReconnect()
    ws.onerror = () => ws.close()
  }

  private kick() {
    if (this.watchdog) clearTimeout(this.watchdog)
    this.watchdog = setTimeout(() => this.ws?.close(), this.heartbeatMs * 2.5)
  }

  private scheduleReconnect() {
    if (this.watchdog) clearTimeout(this.watchdog)
    if (this.closed) return
    useConnection.getState().set({ state: this.attempt >= 6 ? 'offline' : 'reconnecting', attempts: this.attempt })
    this.retry = setTimeout(() => this.connect(), backoffMs(this.attempt++))
  }

  private send(msg: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }

  /** Subscribe to a topic (exact or prefix with *). Returns an unsubscribe function. */
  on(topic: string, h: Handler): () => void {
    let set = this.handlers.get(topic)
    if (!set) {
      set = new Set()
      this.handlers.set(topic, set)
      this.send({ op: 'subscribe', topics: [topic] })
    }
    set.add(h)
    return () => {
      set!.delete(h)
      if (set!.size === 0) {
        this.handlers.delete(topic)
        this.send({ op: 'unsubscribe', topics: [topic] })
      }
    }
  }

  close() {
    this.closed = true
    if (this.retry) clearTimeout(this.retry)
    if (this.watchdog) clearTimeout(this.watchdog)
    this.ws?.close()
  }
}

let socket: LiveSocket | null = null
export function getSocket(): LiveSocket {
  if (!socket) {
    socket = new LiveSocket()
    socket.connect()
  }
  return socket
}
