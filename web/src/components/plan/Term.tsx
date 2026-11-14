import { useState, type ReactNode } from 'react'

/** Fallback definitions (the card's own glossary from the backend wins). */
export const GLOSSARY: Record<string, string> = {
  'Stop loss': "An order that closes your trade automatically at a set price, so a loss can't grow beyond what you planned.",
  Target: 'A price where you take profit: close (part of) the trade and lock in the gain.',
  Pip: 'The standard small price step in forex. For EUR/USD 1 pip = 0.0001 (1.0900 → 1.0901).',
  Spread: "The small gap between the buy and sell price – the broker's fee.",
  Lot: 'The trade size unit in forex. 1 lot = 100,000 units of the first currency; 0.01 lots = 1,000.',
  'Break-even': 'Moving your stop loss to your entry price, so the trade can no longer lose money.',
  'Limit order': 'An order that waits for the price to come back to your price (buy lower / sell higher than now).',
  'Stop order': 'An order that only opens the trade if the price moves through your price (a breakout).',
  'Time stop': 'Closing the trade at a set time of day, even if neither the stop nor the target was hit.',
  Sideways: 'The price moves back and forth between a floor and a ceiling without a clear direction.',
  Session: 'The main trading hours of a financial centre: Asian (Tokyo), London and New York.',
  'Get ready': 'The price is close to the planned entry. Prepare the order, but only act if the condition is met.',
  Confidence: 'How many independent checks agree with the trade idea.',
  'Risk vs reward': 'How much you could gain compared with how much you could lose if the stop loss is hit.',
}

/** A word with a tap/hover explanation (works on phones: tap toggles the popover). */
export function Term({ word, children, glossary }: { word: string; children?: ReactNode; glossary?: Record<string, string> }) {
  const [open, setOpen] = useState(false)
  const text = glossary?.[word] ?? GLOSSARY[word]
  if (!text) return <>{children ?? word}</>
  return (
    <span className="relative inline-block">
      <button type="button" title={text} aria-label={`${word}: what is this?`} aria-expanded={open}
        onClick={() => setOpen((o) => !o)} onBlur={() => setOpen(false)}
        className="cursor-help border-b border-dotted border-muted text-left">
        {children ?? word}
      </button>
      {open && (
        <span role="tooltip" className="absolute left-0 top-full z-20 mt-1 w-64 rounded border border-line bg-panel-2 p-2 text-xs font-normal text-fg shadow-lg">
          <b>{word}:</b> {text}
        </span>
      )}
    </span>
  )
}
