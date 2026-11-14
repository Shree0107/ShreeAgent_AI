// The user's chart drawings: model, geometry and hit-testing (pure functions, unit-tested).
// Points are stored as (time, price) so drawings stay put when the timeframe or zoom changes.

export type DrawingType = 'trendline' | 'hline' | 'rect' | 'fib' | 'channel' | 'text'

export interface DPoint {
  time: number // unix seconds
  price: number
}

export interface Drawing {
  id: string
  type: DrawingType
  points: DPoint[]
  text?: string | null
  color?: string | null
}

export const TOOLS: { type: DrawingType; label: string; icon: string; points: number; help: string }[] = [
  { type: 'trendline', label: 'Trendline', icon: '╱', points: 2, help: 'Click the start, then the end' },
  { type: 'hline', label: 'Horizontal line', icon: '─', points: 1, help: 'Click the price level' },
  { type: 'rect', label: 'Zone', icon: '▭', points: 2, help: 'Click one corner, then the opposite corner' },
  { type: 'fib', label: 'Fibonacci', icon: 'ℱ', points: 2, help: 'Click the swing start, then the swing end' },
  { type: 'channel', label: 'Parallel channel', icon: '⫽', points: 3, help: 'Click the line start and end, then a point for the parallel line' },
  { type: 'text', label: 'Text note', icon: 'T', points: 1, help: 'Click where the note goes' },
]

export const pointsNeeded = (t: DrawingType) => TOOLS.find((x) => x.type === t)!.points

export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]

/** Fibonacci retracement prices from the first point (0%) to the second (100%). */
export function fibLevels(a: DPoint, b: DPoint): { level: number; price: number }[] {
  return FIB_LEVELS.map((level) => ({ level, price: b.price + (a.price - b.price) * level }))
}

/** Third point of a channel -> the parallel line through it: same slope as a->b, shifted by the price offset. */
export function channelOffset(a: DPoint, b: DPoint, c: DPoint): number {
  if (b.time === a.time) return c.price - a.price
  const slope = (b.price - a.price) / (b.time - a.time)
  return c.price - (a.price + slope * (c.time - a.time))
}

// ---------- time <-> bar index (logical) ----------
/** Fractional bar index of a time: exact on bars, interpolated between them, extrapolated beyond the ends. */
export function timeToLogical(t: number, times: number[], barSeconds: number): number {
  const n = times.length
  if (!n) return 0
  if (t <= times[0]) return (t - times[0]) / barSeconds
  if (t >= times[n - 1]) return n - 1 + (t - times[n - 1]) / barSeconds
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= t) lo = mid
    else hi = mid
  }
  return lo + (t - times[lo]) / (times[hi] - times[lo])
}

/** Inverse of timeToLogical. */
export function logicalToTime(l: number, times: number[], barSeconds: number): number {
  const n = times.length
  if (!n) return 0
  if (l <= 0) return times[0] + l * barSeconds
  if (l >= n - 1) return times[n - 1] + (l - (n - 1)) * barSeconds
  const i = Math.floor(l)
  return times[i] + (l - i) * (times[i + 1] - times[i])
}

// ---------- hit testing (screen pixels) ----------
export interface XY {
  x: number
  y: number
}

export function distToSegment(p: XY, a: XY, b: XY): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  const t = len2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2)) : 0
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

/** Screen shapes of a drawing (segments and a fill box) for drawing and hit testing. */
export interface Shape {
  segments: [XY, XY][]
  box?: { x1: number; y1: number; x2: number; y2: number }
  labels: { x: number; y: number; text: string }[]
}

export function shapeOf(d: Drawing, toXY: (p: DPoint) => XY | null, width: number): Shape | null {
  const pts = d.points.map(toXY)
  if (pts.some((p) => p === null)) return null
  const P = pts as XY[]
  switch (d.type) {
    case 'hline':
      return { segments: [[{ x: 0, y: P[0].y }, { x: width, y: P[0].y }]], labels: [] }
    case 'trendline':
      return P.length < 2 ? null : { segments: [[P[0], P[1]]], labels: [] }
    case 'rect': {
      if (P.length < 2) return null
      const [x1, x2] = [Math.min(P[0].x, P[1].x), Math.max(P[0].x, P[1].x)]
      const [y1, y2] = [Math.min(P[0].y, P[1].y), Math.max(P[0].y, P[1].y)]
      return { box: { x1, y1, x2, y2 }, segments: [[{ x: x1, y: y1 }, { x: x2, y: y1 }], [{ x: x2, y: y1 }, { x: x2, y: y2 }],
        [{ x: x2, y: y2 }, { x: x1, y: y2 }], [{ x: x1, y: y2 }, { x: x1, y: y1 }]], labels: [] }
    }
    case 'fib': {
      if (P.length < 2) return null
      const levels = fibLevels(d.points[0], d.points[1])
      const x1 = Math.min(P[0].x, P[1].x)
      const segs: [XY, XY][] = []
      const labels: Shape['labels'] = []
      for (const lv of levels) {
        const y = toXY({ time: d.points[0].time, price: lv.price })?.y
        if (y === undefined) continue
        segs.push([{ x: x1, y }, { x: width, y }])
        labels.push({ x: x1 + 4, y: y - 3, text: `${(lv.level * 100).toFixed(1)}%  ${lv.price.toFixed(5)}` })
      }
      return { segments: segs, labels }
    }
    case 'channel': {
      if (P.length < 2) return null
      const segs: [XY, XY][] = [[P[0], P[1]]]
      if (d.points.length === 3) {
        const off = channelOffset(d.points[0], d.points[1], d.points[2])
        const a2 = toXY({ time: d.points[0].time, price: d.points[0].price + off })
        const b2 = toXY({ time: d.points[1].time, price: d.points[1].price + off })
        if (a2 && b2) segs.push([a2, b2])
      }
      return { segments: segs, labels: [] }
    }
    case 'text':
      return { segments: [], labels: [{ x: P[0].x, y: P[0].y, text: d.text || 'Note' }] }
  }
}

/** Id of the drawing under the cursor (within `tol` pixels), topmost first. */
export function hitTest(drawings: Drawing[], at: XY, toXY: (p: DPoint) => XY | null, width: number, tol = 6): string | null {
  for (let i = drawings.length - 1; i >= 0; i--) {
    const s = shapeOf(drawings[i], toXY, width)
    if (!s) continue
    if (s.segments.some(([a, b]) => distToSegment(at, a, b) <= tol)) return drawings[i].id
    if (s.box && at.x >= s.box.x1 && at.x <= s.box.x2 && at.y >= s.box.y1 && at.y <= s.box.y2) return drawings[i].id
    if (s.labels.some((l) => Math.abs(at.x - l.x - 30) <= 40 && Math.abs(at.y - l.y) <= 10) && drawings[i].type === 'text') return drawings[i].id
  }
  return null
}

export const newId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4)

// ---------- persistence ----------
export async function loadDrawings(symbol: string): Promise<Drawing[]> {
  const r = await fetch(`/api/drawings?symbol=${encodeURIComponent(symbol)}`)
  if (!r.ok) throw new Error(`Couldn't load drawings (${r.status})`)
  return r.json()
}

export async function saveDrawings(symbol: string, drawings: Drawing[]): Promise<void> {
  const r = await fetch(`/api/drawings?symbol=${encodeURIComponent(symbol)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(drawings),
  })
  if (!r.ok) throw new Error(`Couldn't save drawings (${r.status})`)
}
