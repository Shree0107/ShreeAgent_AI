// Draws the AI analysis overlay (zones, lines, levels, labels) beneath the user's own drawings.
import type { CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, PrimitivePaneViewZOrder,
  SeriesAttachedParameter, SeriesType, Time,
} from 'lightweight-charts'
import { timeToLogical } from '../../lib/drawings'
import type { OShape, TP } from '../../lib/overlay'

export class OverlayPrimitive implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null
  series: ISeriesApi<SeriesType> | null = null
  private requestUpdate: (() => void) | null = null
  shapes: OShape[] = []
  times: number[] = []
  barSeconds = 60
  textColor = '#8b93a3'

  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as IChartApi
    this.series = p.series as ISeriesApi<SeriesType>
    this.requestUpdate = p.requestUpdate
  }

  detached() {
    this.chart = this.series = this.requestUpdate = null
  }

  set(shapes: OShape[], times: number[], barSeconds: number, textColor: string) {
    Object.assign(this, { shapes, times, barSeconds, textColor })
    this.requestUpdate?.()
  }

  x(t: number | 'right', width: number): number | null {
    if (t === 'right') return width
    if (!this.chart) return null
    return this.chart.timeScale().logicalToCoordinate(timeToLogical(t, this.times, this.barSeconds) as Logical)
  }

  y(p: number): number | null {
    return this.series?.priceToCoordinate(p) ?? null
  }

  xy(p: TP, width: number) {
    const x = this.x(p.time, width)
    const y = this.y(p.price)
    return x === null || y === null ? null : { x, y }
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [{ zOrder: (): PrimitivePaneViewZOrder => 'normal', renderer: () => new OverlayRenderer(this) }]
  }
}

class OverlayRenderer implements IPrimitivePaneRenderer {
  private o: OverlayPrimitive
  constructor(o: OverlayPrimitive) {
    this.o = o
  }

  draw(target: CanvasRenderingTarget2D) {
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const W = mediaSize.width
      ctx.font = '11px Inter, system-ui, sans-serif'
      // Skip any label that would overlap one already drawn (dense charts stay readable).
      const placed: { x: number; y: number; w: number }[] = []
      const label = (text: string, x: number, y: number, color: string) => {
        const w = ctx.measureText(text).width
        if (placed.some((p) => Math.abs(p.y - y) < 12 && x < p.x + p.w + 4 && p.x < x + w + 4)) return
        placed.push({ x, y, w })
        ctx.fillStyle = color
        ctx.fillText(text, x, y)
      }
      for (const s of this.o.shapes) {
        ctx.setLineDash('dash' in s && s.dash ? [5, 4] : [])
        if (s.kind === 'box') {
          const x1 = this.o.x(s.t1, W) ?? 0
          const x2 = this.o.x(s.t2, W) ?? W
          const y1 = this.o.y(Math.max(s.p1, s.p2))
          const y2 = this.o.y(Math.min(s.p1, s.p2))
          if (y1 === null || y2 === null) continue
          const left = Math.max(0, Math.min(x1, x2))
          ctx.fillStyle = s.fill
          ctx.fillRect(left, y1, Math.max(x1, x2) - left, Math.max(1, y2 - y1))
          if (s.stroke) {
            ctx.strokeStyle = s.stroke
            ctx.lineWidth = 1
            ctx.strokeRect(left, y1, Math.max(x1, x2) - left, Math.max(1, y2 - y1))
          }
          if (s.label) label(s.label, left + 4, y1 + 11, this.o.textColor)
        } else if (s.kind === 'hline') {
          const y = this.o.y(s.price)
          if (y === null) continue
          const x0 = s.from !== undefined ? Math.max(0, this.o.x(s.from, W) ?? 0) : 0
          ctx.strokeStyle = s.color
          ctx.lineWidth = s.width ?? 1
          ctx.beginPath()
          ctx.moveTo(x0, y)
          ctx.lineTo(W, y)
          ctx.stroke()
          if (s.label) label(s.label, Math.max(x0 + 4, W - ctx.measureText(s.label).width - 70), y - 3, s.color)
        } else if (s.kind === 'line') {
          const a = this.o.xy(s.a, W)
          const b = this.o.xy(s.b, W)
          if (!a || !b) continue
          ctx.strokeStyle = s.color
          ctx.lineWidth = s.width ?? 1
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
          if (s.label) label(s.label, (a.x + b.x) / 2, (a.y + b.y) / 2 - 4, s.color)
        } else if (s.kind === 'text') {
          const p = this.o.xy(s.at, W)
          if (!p) continue
          ctx.font = '600 10px Inter, system-ui, sans-serif'
          const w = ctx.measureText(s.text).width
          label(s.text, p.x - w / 2, s.below ? p.y + 14 : p.y - 6, s.color)
          ctx.font = '11px Inter, system-ui, sans-serif'
        }
      }
      ctx.setLineDash([])
    })
  }
}
