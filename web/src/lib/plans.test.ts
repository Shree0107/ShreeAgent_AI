import { describe, expect, it } from 'vitest'
import { decisionOf, fmtDist, liveDistances, matchesFilter, planShapes, staleness, timelineStep, type PlanCard } from './plans'
import { buyCard, waitCard } from './__fixtures__/plans'

describe('plan helpers', () => {
  it('maps action + state to the decision label', () => {
    expect(decisionOf({ action: 'BUY', state: 'waiting' })).toEqual({ label: 'BUY', tone: 'up' })
    expect(decisionOf({ action: 'SELL', state: 'in_trade' })).toEqual({ label: 'SELL', tone: 'down' })
    expect(decisionOf({ action: 'BUY', state: 'ready' })).toEqual({ label: 'GET READY', tone: 'ready' })
    expect(decisionOf({ action: 'WAIT', state: 'market_closed' })).toEqual({ label: 'WAIT', tone: 'wait' })
  })

  it('filters by decision', () => {
    const ready = { ...buyCard(), state: 'ready' } as PlanCard
    expect(matchesFilter(ready, 'ready') && matchesFilter(ready, 'buy')).toBe(true)
    expect(matchesFilter(waitCard(), 'wait') && !matchesFilter(waitCard(), 'buy')).toBe(true)
  })

  it('computes live distances in pips (forex) and % (stocks)', () => {
    expect(fmtDist(1.0956, 1.095, 0.0001)).toBe('6 pips')
    expect(fmtDist(200, 202, null)).toBe('1.0%')
    const d = liveDistances(buyCard(), 1.0956)
    expect(d.entry).toBe('6 pips')
    expect(d.sentence).toBe('Price is 6 pips away from entry')
    const inTrade = liveDistances({ ...buyCard(), state: 'in_trade' } as PlanCard, 1.0960)
    expect(inTrade.sentence).toBe('Price is 21 pips from target 1 and 29 pips from the stop loss')
    expect(liveDistances(waitCard(), 1.09).sentence).toBeNull()
  })

  it('greys cards older than one 15M candle or with a closed/stale feed', () => {
    const now = Date.parse('2026-11-11T12:05:00Z')
    expect(staleness(buyCard(), now).stale).toBe(false)
    expect(staleness(buyCard(), now + 20 * 60_000).label).toMatch(/Out of date/)
    expect(staleness(buyCard(), now, 'closed').label).toMatch(/Market closed/)
    expect(staleness(buyCard(), now, 'stale').stale).toBe(true)
    expect(staleness({ ...waitCard(), state: 'market_closed' }, now).stale).toBe(true)
  })

  it('places the status timeline step', () => {
    expect(timelineStep('waiting').step).toBe(0)
    expect(timelineStep('ready').step).toBe(1)
    expect(timelineStep('in_trade').step).toBe(3)
    expect(timelineStep('tp1_hit')).toEqual({ step: 3, result: 'Target 1 hit – running to target 2' })
    expect(timelineStep('sl_hit')).toEqual({ step: 4, result: 'Stop loss hit' })
  })

  it('draws entry, stop and targets on the mini chart', () => {
    const labels = planShapes(buyCard()).map((s) => ('label' in s ? s.label : ''))
    expect(labels).toEqual(['Entry zone', 'Entry', 'Stop loss', 'Target 1', 'Target 2'])
    expect(planShapes(waitCard()).map((s) => ('label' in s ? s.label : ''))).toEqual(['Top of range', 'Bottom of range'])
  })
})
