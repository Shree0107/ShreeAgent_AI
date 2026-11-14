import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const handlers: Record<string, (d: unknown) => void> = {}
vi.mock('../lib/ws', () => ({ getSocket: () => ({ on: (t: string, h: (d: unknown) => void) => { handlers[t] = h; return () => {} } }) }))

describe('AlertsBell', () => {
  it('lists incoming trade alerts and counts unread ones', async () => {
    const { AlertsBell } = await import('./AlertsBell')
    render(<AlertsBell />)
    act(() => handlers.alert({ title: '🚀 Entry triggered: EUR/USD', body: 'Stop loss: 1.0931', type: 'entry_triggered', symbol: 'EUR/USD', ts: 1_700_000_000 }))
    expect(screen.getByRole('button', { name: 'Alerts (1 new)' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Alerts/ }))
    expect(screen.getByText('🚀 Entry triggered: EUR/USD')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alerts' })).toBeInTheDocument()   // read now
  })
})
