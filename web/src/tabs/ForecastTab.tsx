// Forecast tab (phase 9): TimesFM-3 forecast with 50% / 80% ranges, plain summary, model-vs-baselines verdict,
// live accuracy and agreement with the trade plan. Forecasts are made in the background at each candle close;
// this page only reads the cached one and refetches when the server announces a new one.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ForecastChart } from '../components/forecast/ForecastChart'
import { AccuracyCard, AgreementCard, SummaryCard, VerdictCard } from '../components/forecast/Panels'
import { useNow } from '../components/TopBar'
import { api } from '../lib/api'
import {
  FORECAST_TFS, fmtAge, fmtTime, forecastApi, isOutdated, secondsToUpdate,
} from '../lib/forecast'
import { decimalsFor, fmtCountdown } from '../lib/format'
import { useApp } from '../lib/store'
import { getSocket } from '../lib/ws'

const TF_KEY = 'sa-forecast-tf'
function savedTf(): string {
  try {
    const v = localStorage.getItem(TF_KEY)
    return FORECAST_TFS.some((t) => t.id === v) ? (v as string) : '1h'
  } catch {
    return '1h'
  }
}

export default function ForecastTab() {
  const { symbol, theme } = useApp()
  const [tf, setTfState] = useState(savedTf)
  const [details, setDetails] = useState(false)
  const setTf = (v: string) => {
    setTfState(v)
    try {
      localStorage.setItem(TF_KEY, v)
    } catch {
      /* not remembered */
    }
  }
  const qc = useQueryClient()
  const now = useNow(1000)
  const { data: supported } = useQuery({ queryKey: ['timeframes'], queryFn: api.timeframes, staleTime: Infinity })

  const live = useQuery({
    queryKey: ['forecast-live', symbol, tf],
    queryFn: () => forecastApi.live(symbol, tf),
    // poll fast while a forecast is being made, slowly otherwise (the WebSocket usually beats both)
    refetchInterval: (q) => (q.state.data?.refresh_job ? 4000 : 60_000),
  })
  const d = live.data
  const madeAt = d?.forecast?.made_at
  const acc = useQuery({ queryKey: ['forecast-acc', symbol, tf, madeAt], queryFn: () => forecastApi.accuracy(symbol, tf) })
  const ag = useQuery({ queryKey: ['forecast-agree', symbol, tf, madeAt], queryFn: () => forecastApi.agreement(symbol, tf),
                        refetchInterval: 5 * 60_000 })
  const candles = useQuery({ queryKey: ['forecast-candles', symbol, tf, d?.forecast?.last_bar_time],
                             queryFn: () => api.candles(symbol, tf, 300) })

  // A new forecast or a finished job for this symbol/timeframe: refetch right away.
  useEffect(() => {
    const s = getSocket()
    const refetch = () => qc.invalidateQueries({ queryKey: ['forecast-live', symbol, tf] })
    const off1 = s.on(`forecast:${symbol}:${tf}`, refetch)
    const off2 = s.on('job', (data) => {
      const key = (data as { key?: string })?.key ?? ''
      if (key.startsWith(`fclive:${symbol}:${tf}:`)) refetch()
    })
    return () => {
      off1()
      off2()
    }
  }, [qc, symbol, tf])

  // When the next candle should have closed, ask the server (it starts the refresh job).
  const wait = d ? secondsToUpdate(d, now) : null
  const due = !!d && wait === null
  useEffect(() => {
    if (due) live.refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [due])

  const decimals = decimalsFor(symbol, d?.forecast?.last_close)
  const outdated = d ? isOutdated(d, now) : false
  const working = !!d?.refresh_job

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-2 text-lg font-semibold">{symbol} forecast</h2>
        <div className="flex overflow-hidden rounded-md border border-line" role="group" aria-label="Forecast timeframe">
          {FORECAST_TFS.map((t) => (
            <button key={t.id} onClick={() => setTf(t.id)} aria-pressed={tf === t.id}
              disabled={supported ? !supported.includes(t.id) : false}
              title={supported && !supported.includes(t.id) ? 'No data for this timeframe from the current price source' : undefined}
              className={`px-3 py-1 text-xs font-medium disabled:opacity-40 ${tf === t.id ? 'bg-accent text-white' : 'text-muted hover:bg-panel-2 hover:text-fg'}`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-x-3 text-xs text-muted" data-testid="freshness">
          {d?.forecast && (
            <span className={outdated ? 'text-wait' : ''}>
              Made {fmtTime(d.forecast.made_at)} ({fmtAge(d.age_s ?? 0)}) from the candle of {fmtTime(d.forecast.last_bar_time)}
            </span>
          )}
          <span>
            {working ? 'Updating now…'
              : wait !== null ? `Next update in ${fmtCountdown(wait)}`
              : d?.forecast ? 'Waiting for the next candle (the market may be closed)' : ''}
          </span>
          <button className="rounded border border-line px-2 py-0.5 hover:text-fg" onClick={() => setDetails((v) => !v)}
            aria-expanded={details}>
            {details ? 'Hide details' : 'Show details'}
          </button>
        </div>
      </div>

      {live.isError && (
        <p className="rounded border border-line bg-panel p-3 text-sm text-down" role="alert">
          Could not load the forecast: {(live.error as Error).message}
        </p>
      )}
      {d?.last_error && !d.forecast && (
        <p className="rounded border border-line bg-panel p-3 text-sm text-down" role="alert">
          The last forecast attempt failed: {d.last_error}
        </p>
      )}

      <div className="relative h-[320px] rounded-lg border border-line bg-panel sm:h-[420px]" data-testid="forecast-chart">
        <ForecastChart candles={candles.data?.candles ?? []} forecast={d?.forecast ?? null} decimals={decimals}
          intraday={tf !== '1d'} theme={theme} outdated={outdated} />
        {(!d || !d.forecast) && !live.isError && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted">
            {live.isLoading ? 'Loading…' : 'Making the first forecast… (the model can take a minute to start)'}
          </div>
        )}
        <div className="pointer-events-none absolute left-2 top-2 flex gap-3 text-[11px] text-muted">
          <span><span className="text-accent">- -</span> most likely path</span>
          <span><span className="inline-block h-2 w-3 bg-accent/40 align-middle" /> middle half of outcomes</span>
          <span><span className="inline-block h-2 w-3 bg-accent/15 align-middle" /> 4 in 5 outcomes</span>
        </div>
      </div>

      {d?.forecast && <SummaryCard d={d} outdated={outdated} />}

      <div className="grid gap-3 md:grid-cols-2">
        <AgreementCard ag={ag.data} outdated={outdated} />
        <VerdictCard check={d?.check ?? null} variatesText={d?.variates_text} details={details} />
      </div>
      <AccuracyCard acc={acc.data} decimals={decimals} details={details} />

      {details && d?.forecast && (
        <p className="text-xs text-muted" data-testid="tech-details">
          Model {d.forecast.model} · inputs: {d.forecast.variates.join(', ')} · {d.horizon} candles ahead ·
          expected change {d.forecast.expected_change_pct}% · chance of ending higher {Math.round(d.forecast.prob_up * 100)}%
        </p>
      )}
    </div>
  )
}
