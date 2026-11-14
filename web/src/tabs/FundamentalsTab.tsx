// Fundamentals tab (phase 8): next-event countdown, calendar, fundamental bias, central banks, currency strength,
// news, and (for stocks) the company's key numbers in plain words.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { CalendarSection, NextEventBanner, type CalFilters } from '../components/fund/Calendar'
import { BiasCard, CentralBanks, NewsFeed, StockNumbers, StrengthMeter } from '../components/fund/Panels'
import { fundApi, userTimeZone } from '../lib/fundApi'
import { useApp } from '../lib/store'

/** Currencies whose news moves the symbol: both sides of a pair (gold/silver: USD), a stock's home currency. */
export function symbolCurrencies(symbol: string): string[] {
  if (symbol.includes('/')) {
    const cs = symbol.split('/').filter((c) => c !== 'XAU' && c !== 'XAG')
    return cs.length ? cs : ['USD']
  }
  if (/\.(NS|BO)$/i.test(symbol)) return ['INR']
  return symbol.includes('.') || symbol.startsWith('^') ? [] : ['USD']
}

export default function FundamentalsTab() {
  const symbol = useApp((s) => s.symbol)
  const isFx = symbol.includes('/')
  const pairCurrencies = symbolCurrencies(symbol)
  const [filters, setFilters] = useState<CalFilters>({ range: 'today', currency: 'pair', impacts: ['high', 'medium', 'low'] })
  const currency = filters.currency === 'pair' ? (pairCurrencies.length ? pairCurrencies.join(',') : undefined)
    : filters.currency === 'all' ? undefined : filters.currency
  const impact = [...filters.impacts, ...(filters.impacts.includes('low') ? ['holiday'] : [])].join(',')
  const tz = userTimeZone()
  const cal = useQuery({
    queryKey: ['fund', 'calendar', symbol, filters.range, currency, impact, tz],
    queryFn: () => fundApi.calendar({ symbol, currencies: currency, impact, range: filters.range, tz }),
    refetchInterval: 5 * 60_000,
  })
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-3 p-3" data-testid="fundamentals-tab">
      <NextEventBanner data={cal.data} loading={cal.isLoading} error={cal.error} symbol={symbol} onReached={() => void cal.refetch()} />
      <div className="grid gap-3 lg:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-3 lg:col-span-2">
          <CalendarSection filters={filters} setFilters={setFilters} data={cal.data} loading={cal.isLoading}
            error={cal.error} symbol={symbol} pairCurrencies={pairCurrencies} />
          {!isFx && <StockNumbers symbol={symbol} />}
          <NewsFeed symbol={symbol} />
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          <BiasCard symbol={symbol} />
          <CentralBanks />
          <StrengthMeter />
        </div>
      </div>
    </div>
  )
}
