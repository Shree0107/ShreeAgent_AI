// Draws the user's drawings (and the one being placed) on the price pane, as a Lightweight Charts primitive.
import type { CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, SeriesAttachedParameter,
  SeriesType, Time,
} from 'lightweight-charts'
import { shapeOf, timeToLogical, type DPoint, type Drawing, type XY } from '../../lib/drawings'

export interface DrawState {
  drawings: Drawing[]
  preview: Drawing | null
  selected: string | null
  times: number[]
  barSeconds: number
  colors: { line: string; selected: string; text: string; fill: string }
}

export class DrawingsPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType> | null = null
  private requestUpdate: (() => void) | null = null
  state: DrawState = { drawings: [], preview: null, selected: null, times: [], barSeconds: 60,
                       colors: { line: '#3b82f6', selected: '#f59e0b', text: '#e6e9ef', fill: 'rgba(59,130,246,0.12)' } }

  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as IChartApi
    this.series = p.series as ISeriesApi<SeriesType>
    this.requestUpdate = p.requestUpdate
  }

  detached() {
    this.chart = this.series = this.requestUpdate = null
  }

  setState(s: Partial<DrawState>) {
    this.state = { ...this.state, ...s }
    this.requestUpdate?.()
  }

  /** (time, price) -> pixel position in the price pane, or null if off-scale. */
  toXY = (p: DPoint): XY | null => {
    if (!this.chart || !this.series) return null
    const l = timeToLogical(p.time, this.state.times, this.state.barSeconds)
    const x = this.chart.timeScale().logicalToCoordinate(l as Logical)
    const y = this.series.priceToCoordinate(p.price)
    return x === null || y === null ? null : { x, y }
  }

  paneWidth(): number {
    return this.chart?.timeScale().width() ?? 0
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [{ renderer: () => new Renderer(this) }]
  }
}

class Renderer implements IPrimitivePaneRenderer {
  private p: DrawingsPrimitive
  constructor(p: DrawingsPrimitive) {
    this.p = p
  }

  draw(target: CanvasRenderingTarget2D) {
    const { drawings, preview, selected, colors } = this.p.state
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const all = preview ? [...drawings, preview] : drawings
      for (const d of all) {
        const s = shapeOf(d, this.p.toXY, mediaSize.width)
        if (!s) continue
        const isSel = d.id === selected
        const color = d.color || (isSel ? colors.selected : colors.line)
        ctx.lineWidth = isSel ? 2.5 : 1.5
        ctx.strokeStyle = color
        ctx.setLineDash(d === preview ? [6, 4] : [])
        if (s.box) {
          ctx.fillStyle = colors.fill
          ctx.fillRect(s.box.x1, s.box.y1, s.box.x2 - s.box.x1, s.box.y2 - s.box.y1)
        }
        ctx.beginPath()
        for (const [a, b] of s.segments) {
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
        }
        ctx.stroke()
        ctx.setLineDash([])
        ctx.fillStyle = d.type === 'text' ? color : colors.text
        ctx.font = d.type === 'text' ? '600 13px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif'
        for (const l of s.labels) ctx.fillText(l.text, l.x, l.y)
        if (isSel) {
          ctx.fillStyle = colors.selected
          for (const pt of d.points) {
            const xy = this.p.toXY(pt)
            if (xy) ctx.fillRect(xy.x - 3, xy.y - 3, 6, 6)
          }
        }
      }
    })
  }
}
