export function fmtPrice(x: number | null | undefined, decimals = 5): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '–'
  return x.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

/** Price precision that matches how the market quotes it (EUR/USD 1.09412, USD/JPY 151.234, stocks 2 dp). */
export function decimalsFor(symbol: string, price: number | null | undefined): number {
  if (symbol.includes('/')) {
    if (symbol.startsWith('XAU')) return 2
    if (symbol.startsWith('XAG')) return 3
    return symbol.endsWith('/JPY') ? 3 : 5
  }
  return price !== null && price !== undefined && price < 1 ? 4 : 2
}

export function fmtPct(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '–'
  return `${x >= 0 ? '+' : ''}${x.toFixed(2)}%`
}

export function fmtCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}
