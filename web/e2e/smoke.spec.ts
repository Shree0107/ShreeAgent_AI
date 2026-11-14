import { expect, test } from '@playwright/test'
import { forexOpen } from '../src/lib/sessions'

test.beforeAll(async ({ request }) => {
  // Warm every endpoint the page calls once, so the timing below measures normal use rather than the first
  // Yahoo download after a server start (that one-off cost is covered by the API's own start-up warm-up).
  const api = 'http://127.0.0.1:8000/api'
  for (const path of ['/timeframes', '/watchlist', '/symbols/resolve?symbol=EUR/USD', '/quote?symbol=EUR/USD',
                      '/candles?symbol=EUR/USD&tf=1h&limit=500', '/candles?symbol=EUR/USD&tf=1d&limit=500']) {
    expect((await request.get(api + path)).ok(), path).toBeTruthy()
  }
})

test('chart loads in under 2 seconds and shows live-looking data', async ({ page }, info) => {
  const t0 = Date.now()
  await page.goto('/')
  // The chart draws on canvases inside the chart container; the OHLC legend appears once candles arrived.
  await expect(page.getByTestId('price-chart').locator('canvas').first()).toBeVisible()
  await expect(page.getByText(/^O\s/).first()).toBeVisible()
  const ms = Date.now() - t0
  console.log(`[${info.project.name}] chart visible after ${ms} ms`)
  expect(ms).toBeLessThan(2000)

  await expect(page.getByRole('tab')).toHaveCount(5)
  await expect(page.getByText(/session|closed|quiet/i).first()).toBeVisible()
  await page.screenshot({ path: `test-results/chart-${info.project.name}-dark.png` })

  // Light theme
  await page.getByTitle('Switch light / dark').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.screenshot({ path: `test-results/chart-${info.project.name}-light.png` })
})

test('timeframe, chart type and indicators', async ({ page }, info) => {
  await page.goto('/')
  await expect(page.getByText(/^O\s/).first()).toBeVisible()
  await page.getByRole('button', { name: 'D', exact: true }).click()
  await page.getByRole('button', { name: 'Heikin Ashi' }).click()
  await page.getByRole('button', { name: /Indicators/ }).click()
  await page.getByLabel('MACD').check()
  await page.getByLabel('Bollinger Bands').check()
  await page.keyboard.press('Escape')
  await page.getByTestId('price-chart').click()
  await expect(page.getByText(/candles · source/)).toBeVisible()
  await page.screenshot({ path: `test-results/chart-${info.project.name}-daily-ha.png` })
})

test('live status arrives over the WebSocket and intraday timeframes load', async ({ page }, info) => {
  await page.goto('/')
  // The status comes from the server via /ws: it must leave "Reconnecting" and never be Offline.
  // Weekend -> "Market closed"; forex hours -> "Live" (OANDA) or "Delayed" (Yahoo). Never stale-as-live.
  const expected = forexOpen(new Date()) ? /Live|Delayed/ : /Market closed/
  await expect(page.getByTestId('status-dot')).toHaveText(expected, { timeout: 30_000 })
  const status = await page.getByTestId('status-dot').textContent()
  console.log(`[${info.project.name}] feed status: ${status}`)
  await page.getByRole('button', { name: '15m', exact: true }).click()
  await expect(page.getByText(/candles · /)).toBeVisible()
  await expect(page.getByText(/next candle in \d+:\d\d/)).toBeVisible()
  await page.screenshot({ path: `test-results/chart-${info.project.name}-15m.png` })
})
