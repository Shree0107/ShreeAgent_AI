import { describe, expect, it } from 'vitest'
import { activeSessions, forexOpen, secondsToCandleClose, sessionLabel } from './sessions'

describe('trading sessions', () => {
  it('winter: London 08-17 UTC, New York 13-22 UTC', () => {
    // Wed 14 Jan 2026 (no daylight saving anywhere)
    expect(activeSessions(new Date('2026-01-14T07:30:00Z'))).toEqual(['Asian'])
    expect(activeSessions(new Date('2026-01-14T08:30:00Z'))).toEqual(['Asian', 'London']) // Tokyo open until 09:00 UTC
    expect(activeSessions(new Date('2026-01-14T09:30:00Z'))).toEqual(['London'])
    expect(sessionLabel(new Date('2026-01-14T14:00:00Z'))).toBe('London–New York overlap')
    expect(activeSessions(new Date('2026-01-14T21:30:00Z'))).toEqual(['New York'])
    expect(sessionLabel(new Date('2026-01-14T22:30:00Z'))).toBe('Between sessions (quiet)')
  })
  it('summer time moves London and New York one hour earlier in UTC', () => {
    // Wed 15 Jul 2026: London = UTC+1, New York = UTC-4
    expect(activeSessions(new Date('2026-07-15T07:30:00Z'))).toContain('London')
    expect(activeSessions(new Date('2026-07-15T12:30:00Z'))).toEqual(['London', 'New York'])
  })
  it('weekend is closed', () => {
    expect(forexOpen(new Date('2026-11-14T12:00:00Z'))).toBe(false) // Saturday
    expect(sessionLabel(new Date('2026-11-14T12:00:00Z'))).toMatch(/closed/)
    expect(forexOpen(new Date('2026-11-15T23:00:00Z'))).toBe(true) // Sunday evening NY open
  })
  it('countdown to the next candle close', () => {
    expect(secondsToCandleClose(900, 1_000_000_000)).toBe(900 - (1_000_000_000 % 900))
    expect(secondsToCandleClose(900, 900 * 5 + 1)).toBe(899)
  })
})
