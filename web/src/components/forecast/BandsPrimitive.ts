// Fills the 80% (q10-q90) and 50% (q25-q75) forecast ranges as shaded areas behind the median line.
import type { CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, PrimitivePaneViewZOrder,
  SeriesAttachedParameter, SeriesType, Time, UTCTimestamp,
} from 'lightweight-charts'

export interface BandPoint {
  time: number
  lo: number
  hi: number
}

export interface Band {
  points: BandPoint[]
  fill: string
}

export class BandsPrimitive implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null
  series: ISeriesApi<SeriesType> | null = null
  private requestUpdate: (() => void) | null = null
  bands: Band[] = []

  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as IChartApi
    this.series = p.series as ISeriesApi<SeriesType>
    this.requestUpdate = p.requestUpdate
  }

  detached() {
    this.chart = this.series = this.requestUpdate = null
  }

  set(bands: Band[]) {
    this.bands = bands
    this.requestUpdate?.()
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [{ zOrder: (): PrimitivePaneViewZOrder => 'bottom', renderer: () => new BandsRenderer(this) }]
  }
}

class BandsRenderer implements IPrimitivePaneRenderer {
  private p: BandsPrimitive
  constructor(p: BandsPrimitive) {
    this.p = p
  }

  draw(target: CanvasRenderingTarget2D) {
    const { chart, series } = this.p
    if (!chart || !series) return
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      for (const band of this.p.bands) {
        const top: { x: number; y: number }[] = []
        const bottom: { x: number; y: number }[] = []
        for (const pt of band.points) {
          const x = chart.timeScale().timeToCoordinate(pt.time as UTCTimestamp)
          const yh = series.priceToCoordinate(pt.hi)
          const yl = series.priceToCoordinate(pt.lo)
          if (x === null || yh === null || yl === null) continue
          top.push({ x, y: yh })
          bottom.push({ x, y: yl })
        }
        if (top.length < 2) continue
        ctx.beginPath()
        ctx.moveTo(top[0].x, top[0].y)
        for (const p of top.slice(1)) ctx.lineTo(p.x, p.y)
        for (const p of bottom.reverse()) ctx.lineTo(p.x, p.y)
        ctx.closePath()
        ctx.fillStyle = band.fill
        ctx.fill()
      }
    })
  }
}
