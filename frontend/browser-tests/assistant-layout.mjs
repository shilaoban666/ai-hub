import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const source = await readFile('public/embed/assistant.js', 'utf8')
const icon = await readFile('public/embed/icons/assistant-core.svg', 'utf8')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const page = await browser.newPage()
  await page.addInitScript(() => {
    if (location.search.includes('fallback')) Object.defineProperty(HTMLElement.prototype, 'showPopover', { value: undefined, configurable: true })
  })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('https://layout.test/**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('.js')) return route.fulfill({ contentType: 'text/javascript; charset=utf-8', body: source })
    if (url.pathname.endsWith('.svg')) return route.fulfill({ contentType: 'image/svg+xml', body: icon })
    const tall = url.searchParams.has('tall')
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><style>
      body{margin:0;display:flex;gap:16px}main{width:100%;flex-shrink:0;height:${tall ? '1800px' : '100vh'};background:#f6f7f8}
      #action{position:fixed;left:15px;top:15px}
      </style></head><body><main id="content"><button id="action" onclick="this.dataset.clicked='yes'">Business action</button></main></body></html>` })
  })
  const geometry = () => page.evaluate(() => {
    const box = document.querySelector('#content').getBoundingClientRect()
    return {
      width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight,
      bodyWidth: document.body.scrollWidth, bodyHeight: document.body.scrollHeight,
      x: box.x, y: box.y, contentWidth: box.width, contentHeight: box.height,
      htmlStyle: document.documentElement.getAttribute('style'), bodyStyle: document.body.getAttribute('style'),
    }
  })
  for (const fallback of [false, true]) {
  for (const [width, height] of [[900, 650], [320, 600], [500, 220]]) {
    for (const tall of [false, true]) {
      await page.setViewportSize({ width, height })
      await page.goto(`https://layout.test/?${tall ? 'tall&' : ''}${fallback ? 'fallback' : ''}`)
      const baseline = await geometry()
      await page.addScriptTag({ url: 'https://layout.test/embed/assistant.js' })
      const button = page.getByRole('button', { name: '打开 AI 助手', exact: true })
      const bubble = page.locator('.greeting')
      assert.equal(await bubble.evaluate(e => e.getClientRects().length), 0, 'An idle greeting must have no layout box')
      assert.deepEqual(await geometry(), baseline, 'Mounting the assistant must not change host layout or scroll dimensions')
      await button.hover()
      await bubble.waitFor({ state: 'visible' })
      assert.deepEqual(await bubble.evaluate(e => [getComputedStyle(e).overflowX, getComputedStyle(e).overflowY]), ['visible', 'visible'], 'Popover default overflow must not turn the speech tail into a scrollbar')
      assert.equal(await bubble.evaluate(e => getComputedStyle(e, '::-webkit-scrollbar').display), 'none', 'The greeting must never render scrollbars')
      assert.equal(await page.locator('#aihub-assistant-root').evaluate(e => getComputedStyle(e).overflowX), 'hidden', 'The widget container must never render a horizontal scrollbar')
      if (!fallback) assert(await bubble.evaluate(e => e.matches(':popover-open')), 'The greeting must be isolated in the browser top layer')
      assert.deepEqual(await geometry(), baseline, 'The greeting must not enlarge the host scroll area')
      await page.keyboard.press('Escape')
      await bubble.waitFor({ state: 'hidden' })
      assert.equal(await bubble.evaluate(e => e.getClientRects().length), 0, 'Dismissed greetings must leave no scrollable box')
      await page.locator('#action').click()
      assert.equal(await page.locator('#action').getAttribute('data-clicked'), 'yes', 'The overlay must not intercept business-page clicks')
      const bounds = await button.boundingBox()
      await page.mouse.move(bounds.x + 24, bounds.y + 24)
      await page.mouse.down()
      await page.mouse.move(width - 10, 30, { steps: 12 })
      await page.mouse.up()
      await page.mouse.move(width / 2, height / 2)
      await button.hover()
      await bubble.waitFor({ state: 'visible' })
      assert.deepEqual(await geometry(), baseline, 'Dragging and edge placement must not enlarge the page')
      await button.click()
      assert.deepEqual(await geometry(), baseline, 'Opening the assistant must not resize or lock the host page')
      await page.getByRole('button', { name: '收起助手', exact: true }).click()
      if (tall) {
        await page.mouse.move(width / 2, height / 2)
        await page.mouse.wheel(0, 250)
        await page.waitForFunction(() => window.scrollY > 0)
        assert.equal(await page.evaluate(() => document.documentElement.scrollHeight), baseline.height, 'Business-page scrolling must remain available')
      }
    }
  }
  }
  assert.deepEqual(errors, [])
  console.log('Passed: no added page overflow or layout changes; hover, dragging, panels, underlying clicks and existing scrolling across desktop/mobile/short viewports.')
} finally { await browser.close() }
