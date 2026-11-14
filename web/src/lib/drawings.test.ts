import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDrawings } from '../components/chart/useDrawings'
import { channelOffset, distToSegment, fibLevels, hitTest, logicalToTime, shapeOf, timeToLogical, type Drawing } from './drawings'

const times = [1000, 1060, 1120, 1180]

describe('time <-> bar index', () => {
  it('is exact on bars, interpolates between, extrapolates beyond', () => {
    expect(timeToLogical(1060, times, 60)).toBe(1)
    expect(timeToLogical(1090, times, 60)).toBe(1.5)
    expect(timeToLogical(1300, times, 60)).toBe(5) // two bars past the last one
    expect(timeToLogical(880, times, 60)).toBe(-2)
    for (const l of [-2, 0, 1.25, 3, 6.5]) expect(timeToLogical(logicalToTime(l, times, 60), times, 60)).toBeCloseTo(l, 9)
  })
})

describe('geometry', () => {
  it('Fibonacci levels run from the first point (0%) to the second (100%)', () => {
    const lv = fibLevels({ time: 0, price: 1.1 }, { time: 1, price: 1.2 })
    expect(lv.find((l) => l.level === 0)!.price).toBeCloseTo(1.2)
    expect(lv.find((l) => l.level === 1)!.price).toBeCloseTo(1.1)
    expect(lv.find((l) => l.level === 0.618)!.price).toBeCloseTo(1.2 - 0.0618)
  })
  it('channel offset is the vertical distance to the parallel line', () => {
    expect(channelOffset({ time: 0, price: 1 }, { time: 10, price: 2 }, { time: 5, price: 1.2 })).toBeCloseTo(-0.3)
  })
  it('segment distance and hit testing', () => {
    expect(distToSegment({ x: 5, y: 3 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBe(3)
    const toXY = (p: { time: number; price: number }) => ({ x: p.time, y: 100 - p.price })
    const ds: Drawing[] = [
      { id: 'h', type: 'hline', points: [{ time: 0, price: 50 }] },
      { id: 'r', type: 'rect', points: [{ time: 10, price: 90 }, { time: 30, price: 70 }] },
    ]
    expect(hitTest(ds, { x: 200, y: 52 }, toXY, 400)).toBe('h') // horizontal line spans the full width
    expect(hitTest(ds, { x: 20, y: 20 }, toXY, 400)).toBe('r') // inside the zone
    expect(hitTest(ds, { x: 200, y: 20 }, toXY, 400)).toBeNull()
    expect(shapeOf({ id: 'c', type: 'channel', points: [{ time: 0, price: 0 }, { time: 10, price: 10 }, { time: 0, price: 5 }] }, toXY, 400)!.segments).toHaveLength(2)
  })
})

describe('useDrawings', () => {
  afterEach(() => vi.restoreAllMocks())

  function mockServer(initial: Drawing[] = []) {
    const saved: Drawing[][] = []
    globalThis.fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') saved.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify(init?.method === 'PUT' ? [] : initial), { status: 200 })
    }) as typeof fetch
    return saved
  }

  it('places a two-point trendline, selects it, saves it, deletes it', async () => {
    const saved = mockServer()
    const { result } = renderHook(() => useDrawings('EUR/USD'))
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    act(() => result.current.startTool('trendline'))
    act(() => { result.current.addPoint({ time: 1, price: 1.1 }) })
    expect(result.current.pending).toHaveLength(1)
    act(() => result.current.setHover({ time: 2, price: 1.2 }))
    expect(result.current.preview?.points).toHaveLength(2)          // rubber-band preview to the cursor
    act(() => { result.current.addPoint({ time: 3, price: 1.3 }) })
    expect(result.current.drawings).toHaveLength(1)
    expect(result.current.tool).toBeNull()
    expect(result.current.selected).toBe(result.current.drawings[0].id)
    await waitFor(() => expect(saved.at(-1)).toHaveLength(1), { timeout: 2000 })
    act(() => result.current.remove(result.current.drawings[0].id))
    await waitFor(() => expect(saved.at(-1)).toHaveLength(0), { timeout: 2000 })
  })

  it('text notes ask for their text; cancelling the prompt adds nothing', async () => {
    mockServer()
    const { result } = renderHook(() => useDrawings('EUR/USD'))
    act(() => result.current.startTool('text'))
    act(() => { result.current.addPoint({ time: 1, price: 1 }, () => null) })
    expect(result.current.drawings).toHaveLength(0)
    act(() => result.current.startTool('text'))
    act(() => { result.current.addPoint({ time: 1, price: 1 }, () => 'Breakout level') })
    expect(result.current.drawings[0].text).toBe('Breakout level')
  })

  it('loads the saved drawings of the symbol', async () => {
    mockServer([{ id: 'x', type: 'hline', points: [{ time: 1, price: 1.09 }] }])
    const { result } = renderHook(() => useDrawings('EUR/USD'))
    await waitFor(() => expect(result.current.drawings.map((d) => d.id)).toEqual(['x']))
  })
})
