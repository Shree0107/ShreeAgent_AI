// Forex trading sessions in each market's own time zone, so summer/winter time shifts are automatic.
//   Asian (Tokyo)   09:00-18:00 Asia/Tokyo
//   London          08:00-17:00 Europe/London
//   New York        08:00-17:00 America/New_York
// The London-New York overlap is the busiest part of the day for EUR/USD.

export type SessionName = 'Asian' | 'London' | 'New York'

const SESSIONS: { name: SessionName; tz: string; open: number; close: number }[] = [
  { name: 'Asian', tz: 'Asia/Tokyo', open: 9, close: 18 },
  { name: 'London', tz: 'Europe/London', open: 8, close: 17 },
  { name: 'New York', tz: 'America/New_York', open: 8, close: 17 },
]

function localParts(d: Date, tz: string) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23',
  }).formatToParts(d)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return { hour: Number(get('hour')) + Number(get('minute')) / 60, weekday: get('weekday') }
}

/** Forex is closed from Friday 17:00 to Sunday 17:00 New York time. */
export function forexOpen(d: Date): boolean {
  const { hour, weekday } = localParts(d, 'America/New_York')
  if (weekday === 'Sat') return false
  if (weekday === 'Fri' && hour >= 17) return false
  if (weekday === 'Sun' && hour < 17) return false
  return true
}

export function activeSessions(d: Date = new Date()): SessionName[] {
  if (!forexOpen(d)) return []
  return SESSIONS.filter((s) => {
    const { hour, weekday } = localParts(d, s.tz)
    return weekday !== 'Sat' && weekday !== 'Sun' && hour >= s.open && hour < s.close
  }).map((s) => s.name)
}

export function sessionLabel(d: Date = new Date()): string {
  if (!forexOpen(d)) return 'Market closed (weekend)'
  const a = activeSessions(d)
  if (a.includes('London') && a.includes('New York')) return 'London–New York overlap'
  if (a.length === 0) return 'Between sessions (quiet)'
  return `${a.join(' + ')} session`
}

/** Seconds until the next candle of `tfSeconds` closes (candles aligned to UTC, like the data feeds). */
export function secondsToCandleClose(tfSeconds: number, now: number = Date.now() / 1000): number {
  return Math.ceil(tfSeconds - (now % tfSeconds))
}
