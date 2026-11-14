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

test('draw lines on the chart; they are saved and come back after a reload', async ({ page, request }, info) => {
  test.skip(info.project.name === 'mobile', 'drawing with a mouse is a desktop flow')
  const API = 'http://127.0.0.1:8000/api/drawings?symbol=USD%2FCHF'
  const before = await (await request.get(API)).json()           // the user's own drawings: restored at the end
  await request.put(API, { data: [] })
  try {
    await page.addInitScript(() => localStorage.setItem('sa-ui', JSON.stringify({ symbol: 'USD/CHF', tf: '1d' })))
    await page.goto('/')
    await expect(page.getByText(/^O\s/).first()).toBeVisible()
    const box = (await page.getByTestId('price-chart').boundingBox())!
    const at = (fx: number, fy: number) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy })

    await page.getByRole('button', { name: /Draw/ }).click()
    await page.getByRole('menuitem', { name: 'Horizontal line' }).click()
    await expect(page.getByRole('status')).toContainText('Horizontal line')
    await page.mouse.click(at(0.5, 0.3).x, at(0.5, 0.3).y)

    await page.getByRole('button', { name: /Draw/ }).click()
    await page.getByRole('menuitem', { name: 'Trendline' }).click()
    await page.mouse.click(at(0.3, 0.5).x, at(0.3, 0.5).y)
    await page.mouse.move(at(0.6, 0.4).x, at(0.6, 0.4).y)
    await page.mouse.click(at(0.7, 0.35).x, at(0.7, 0.35).y)

    const panel = page.getByRole('complementary', { name: 'My drawings' })
    await expect(panel).toContainText('My drawings (2)')
    await page.screenshot({ path: `test-results/drawings-${info.project.name}.png` })
    await page.waitForTimeout(800)                                  // auto-save is debounced
    await page.reload()
    await expect(page.getByRole('complementary', { name: 'My drawings' })).toContainText('My drawings (2)')
    const saved = await (await request.get(API)).json()
    expect(saved.map((d: { type: string }) => d.type).sort()).toEqual(['hline', 'trendline'])
  } finally {
    await request.put(API, { data: before })
  }
})

test('AI analysis overlay draws on the chart', async ({ page }, info) => {
  await page.addInitScript(() => localStorage.setItem('sa-ui', JSON.stringify({ symbol: 'EUR/USD', tf: '1h' })))
  await page.goto('/')
  await expect(page.getByText(/^O\s/).first()).toBeVisible()
  await page.getByRole('button', { name: /^✨ AI analysis/ }).click()
  await expect(page.getByTestId('regime')).toHaveText(/Trending|Sideways/, { timeout: 30_000 })
  await page.getByRole('button', { name: 'Choose what the AI analysis shows' }).click()
  await page.getByLabel(/Fibonacci/).check()
  await page.getByLabel(/Liquidity/).check()
  await page.getByRole('button', { name: 'Done' }).click()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `test-results/overlay-${info.project.name}.png` })
})
