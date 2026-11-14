// Drawing tool state for one symbol: placing points, preview, selection, delete, and auto-save to the server.
import { useCallback, useEffect, useRef, useState } from 'react'
import { loadDrawings, newId, pointsNeeded, saveDrawings, type DPoint, type Drawing, type DrawingType } from '../../lib/drawings'

export function useDrawings(symbol: string) {
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const [tool, setTool] = useState<DrawingType | null>(null)
  const [pending, setPending] = useState<DPoint[]>([])
  const [hover, setHover] = useState<DPoint | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loaded = useRef<string | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    loaded.current = null
    setDrawings([])
    setPending([])
    setSelected(null)
    loadDrawings(symbol)
      .then((d) => {
        setDrawings(d)
        loaded.current = symbol
      })
      .catch((e: Error) => setError(e.message))
  }, [symbol])

  // Save shortly after any change (debounced), only once this symbol's drawings were loaded.
  useEffect(() => {
    if (loaded.current !== symbol) return
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      saveDrawings(symbol, drawings).then(() => setError(null)).catch((e: Error) => setError(e.message))
    }, 400)
  }, [drawings, symbol])

  const cancel = useCallback(() => {
    setTool(null)
    setPending([])
  }, [])

  const remove = useCallback((id: string) => {
    setDrawings((d) => d.filter((x) => x.id !== id))
    setSelected((s) => (s === id ? null : s))
  }, [])

  /** A click on the chart: add a point to the drawing being placed, or finish it. */
  const addPoint = useCallback((p: DPoint, promptText: () => string | null = () => window.prompt('Note text:')) => {
    if (!tool) return false
    const pts = [...pending, p]
    if (pts.length < pointsNeeded(tool)) {
      setPending(pts)
      return true
    }
    let text: string | null = null
    if (tool === 'text') {
      text = promptText()
      if (!text) {
        cancel()
        return true
      }
    }
    const d: Drawing = { id: newId(), type: tool, points: pts, text }
    setDrawings((all) => [...all, d])
    setSelected(d.id)
    setPending([])
    setTool(null)
    return true
  }, [tool, pending, cancel])

  // While placing: show the drawing so far, with the cursor as the next point.
  const preview: Drawing | null = tool && pending.length && hover
    ? { id: '__preview', type: tool, points: [...pending, hover].slice(0, pointsNeeded(tool)), text: null }
    : tool && tool === 'hline' && hover ? { id: '__preview', type: 'hline', points: [hover] } : null

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return
      if (e.key === 'Escape') {
        cancel()
        setSelected(null)
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selected) remove(selected)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, cancel, remove])

  return {
    drawings, tool, pending, preview, selected, error,
    startTool: (t: DrawingType | null) => {
      setTool(t)
      setPending([])
      setSelected(null)
    },
    addPoint, setHover, setSelected, remove, cancel,
    clearAll: () => {
      setDrawings([])
      setSelected(null)
    },
  }
}
