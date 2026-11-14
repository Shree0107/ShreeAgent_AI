// Example cards shaped like GET /api/plans output (used by the plan tests).
import type { PlanCard } from '../plans'

const DISCLAIMER = 'Analysis only, not financial advice. Always use a stop loss.'

export function buyCard(): PlanCard {
  return {
    symbol: 'EUR/USD', name: 'Euro / US dollar', action: 'BUY', state: 'waiting', setup: 'range_breakout',
    setup_name: 'Breakout from a sideways range', direction: 'long', entry: 1.095, entry_low: 1.0945, entry_high: 1.095,
    entry_type: 'stop', stop: 1.0931, target1: 1.0981, target2: 1.1002, generated_at: '2026-11-11T12:00:00+00:00',
    expires_at: '2026-11-11T14:00:00+00:00', market: 'trending_up', market_text: 'Trending up',
    session_label: 'London session', range: null, scenarios: [], probability: null, confidence: 'Medium',
    size: { currency: 'EUR', lots: 0.05, units: 5000, actual_risk: 8.7, gain_target1: 14.2, gain_target2: 23.8, too_small: false },
    explanation: {
      headline: 'Buy only if the price breaks above 1.0950.',
      why: ["The bigger charts and today's 1-hour chart point up.", 'The 15-minute chart is making higher lows.',
            'Buying pressure is building.'],
      waiting_for: ["The price to rise to 1.0950 – it's 6 pips away."],
      entry_text: 'Buy only if the price breaks above 1.0950', order_text: 'Buy Stop order (breakout)',
      stop_text: '1.0931 (19 pips)', stop_reason: "Beyond the other side of the sideways range: then the breakout has failed.",
      targets: [{ label: 'Target 1', price: 1.0981, text: '1.0981 (+31 pips)' }, { label: 'Target 2', price: 1.1002, text: '1.1002 (+52 pips)' }],
      rr_text: 'You risk 1 to make 1.63 at target 1', rr_money_text: 'You risk €8.70 to make €14.20 at target 1 (€23.80 at target 2)',
      breakeven_text: 'When the price reaches 1.0969 (+1 × your risk), move the stop loss to your entry 1.0950 – then the trade can\'t lose.',
      cancel: ['Cancel if a 15-minute candle closes below 1.0931 before you are in.', "Cancel if the order hasn't filled by 15:00."],
      time_stop_text: 'Close the trade by 21:30 (Berlin time) at the latest – before the New York session ends. This is a same-day trade.',
      probability_text: 'No backtest yet – treat as unproven', time_window_text: 'likely within the next 1–3 hours (rough estimate)',
      confidence_text: 'Confidence MEDIUM – 4 checks agree', news_warning: 'CPI m/m (USD) at 14:30 – no new trades 14:00–15:00.',
      size_text: 'Buy 0.05 lots', size_note: 'If the stop loss is hit you lose about €8.70 (1% of €1,000).',
      stop_money: '−€8.70', tp1_money: '+€14.20', tp2_money: '+€23.80', disclaimer: DISCLAIMER,
    },
    details: {
      mtf: [{ tf: '1d', direction: 'up', score: 70, details: ['EMA21 > EMA50, close above EMA21'] }],
      confirmations: [{ key: 'momentum', plain: 'Buying pressure is building', detail: 'RSI14 61, MACD hist +0.0002', tf: '15m' }],
      gates: [], spread: { pips: 1, live: false, note: 'typical', max: 2 }, score: 62,
    },
    stale: false, price: 1.0944, decimals: 5, pip_size: 0.0001, is_fx: true, plan_state: null, strength: 1062,
  }
}

export function waitCard(): PlanCard {
  return {
    ...buyCard(), action: 'WAIT', state: 'waiting', setup: null, direction: null, entry: null, entry_low: null,
    entry_high: null, entry_type: null, stop: null, target1: null, target2: null, market: 'sideways', market_text: 'Sideways',
    range: { low: 1.0912, high: 1.0948 }, size: null, strength: 40,
    scenarios: [
      { direction: 'long', price: 1.095, likely_pct: 60, entry_type: 'stop', text: 'Buy if it breaks above 1.0950', why: 'Up is more likely (60/40) because the bigger charts are rising.' },
      { direction: 'short', price: 1.091, likely_pct: 40, entry_type: 'stop', text: 'Sell if it breaks below 1.0910', why: '' },
    ],
    explanation: {
      ...buyCard().explanation, headline: 'WAIT – stuck between 1.0912 and 1.0948.',
      why: ['The big picture (daily and 4-hour charts) is rising; today\'s 1-hour chart is without a clear direction.'],
      waiting_for: ['The 1-hour chart has no clear direction today.'], targets: [], cancel: [], news_warning: null,
    },
  }
}
