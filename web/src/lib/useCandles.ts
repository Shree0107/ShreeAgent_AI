import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Candle } from './api'

/** Merge two candle lists by time (later list wins on duplicates), oldest first. */
export function mergeCandles(a: Candle[], b: Candle[]): Candle[] {
  const m = new Map<number, Candle>()
  for (const c of a) m.set(c.time, c)
  for (const c of b) m.set(c.time, c)
  return [...m.values()].sort((x, y) => x.time - y.time)
}

/** Loads the newest 500 candles fast, then pages older ones in when the user scrolls left. */
export function useCandles(symbol: string, tf: string) {
  const [candles, setCandles] = useState<Candle[]>([])
  const [source, setSource] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const hasMore = useRef(true)
  const busy = useRef(false)
  const key = `${symbol}|${tf}`
  const keyRef = useRef(key)

  useEffect(() => {
    keyRef.current = key
    let cancelled = false
    setLoading(true)
    setError(null)
    setCandles([])
    hasMore.current = true
    api.candles(symbol, tf, 500)
      .then((r) => {
        if (cancelled) return
        setCandles(r.candles)
        setSource(r.source)
        hasMore.current = r.has_more
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [key, symbol, tf])

  const loadMore = useCallback(() => {
    if (busy.current || !hasMore.current || !candles.length) return
    busy.current = true
    const k = keyRef.current
    api.candles(symbol, tf, 500, candles[0].time)
      .then((r) => {
        if (keyRef.current !== k) return
        hasMore.current = r.has_more
        setCandles((cur) => mergeCandles(r.candles, cur))
      })
      .catch(() => (hasMore.current = false))
      .finally(() => (busy.current = false))
  }, [candles, symbol, tf])

  /** Apply a live update to the last candle or append a new one (used by the live feed). */
  const applyLive = useCallback((bar: Candle) => setCandles((cur) => mergeCandles(cur, [bar])), [])

  return { candles, source, error, loading, loadMore, applyLive }
}
