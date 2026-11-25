import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const source = await readFile('public/embed/assistant.js', 'utf8')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  for (const fallback of [false, true]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    page.on('pageerror', error => console.error(error.message))
    if (fallback) await page.addInitScript(() => {
      Object.defineProperty(HTMLElement.prototype, 'showPopover', { value: undefined, configurable: true })
    })
    await page.route('https://**/*', route => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith('.js')) return route.fulfill({ contentType: 'text/javascript; charset=utf-8', body: source })
      if (url.pathname.endsWith('.svg')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg"/>' })
      if (url.pathname === '/chat') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<!doctype html><style>html,body{margin:0;height:100%;overflow:hidden}#messages{height:100%;overflow:auto;overscroll-behavior:contain}</style><div id="messages"><div style="height:4000px">Chat content</div></div><script>parent.postMessage({protocol:'aihub-embed-v1',type:'ready'},'https://host.test')</script>` })
      if (url.pathname === '/business') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: '<!doctype html><style>body{margin:0;height:4000px;background:#eee}</style>Business frame' })
      return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<!doctype html><style>body{margin:0;height:4000px}#nested{position:fixed;top:10px;left:10px;width:300px;height:300px;overflow:auto}#business{position:fixed;top:10px;left:350px;width:400px;height:400px}</style><div id="nested"><div style="height:3000px">Nested content</div></div><iframe id="business" src="/business"></iframe><script src="/assistant.js" data-aihub-url="https://chat.test/chat"></script>` })
    })
    await page.goto('https://host.test/')
    assert.equal(await page.locator('#aihub-assistant-root').count(), 1, 'Assistant script must mount')
    const launcher = page.getByRole('button', { name: '打开 AI 助手', exact: true })
    const close = page.getByRole('button', { name: '收起助手', exact: true })
    const hostTop = () => page.evaluate(() => scrollY)
    async function wheelAt(x, y, getTop, label) {
      const before = await getTop()
      await page.mouse.move(x, y)
      await page.mouse.wheel(0, 180)
      await page.waitForTimeout(300)
      assert(await getTop() > before, label)
    }
    for (let cycle = 0; cycle < 3; cycle++) {
      await launcher.click()
      const messages = page.frameLocator('iframe[title="AI Hub 对话"]').locator('#messages')
      await messages.waitFor()
      await wheelAt(1100, 200, () => messages.evaluate(el => el.scrollTop), 'Cross-origin chat must scroll after reopening')
      const chatTop = await messages.evaluate(el => el.scrollTop)
      const businessTop = await hostTop()
      await wheelAt(150, 150, () => page.locator('#nested').evaluate(el => el.scrollTop), 'Nested business region must scroll with drawer open')
      await wheelAt(450, 150, () => page.frameLocator('#business').locator('html').evaluate(() => scrollY), 'Business iframe must scroll with drawer open')
      assert.equal(await hostTop(), businessTop, 'Nested scrolling must leave host stationary')
      await wheelAt(800, 600, hostTop, 'Host must scroll with drawer open')
      assert.equal(await messages.evaluate(el => el.scrollTop), chatTop, 'Host scrolling must leave chat stationary')
      await close.click()
      await launcher.hover()
      const bubble = await page.locator('.greeting').boundingBox()
      await wheelAt(bubble.x + 30, bubble.y + 25, hostTop, 'Greeting must pass scrolling through to the host')
      assert.equal(await page.locator('.drag-shield').count(), 0, 'No drag shield may remain after close')
    }
    await page.close()
  }
  console.log('Passed: repeated reopen, cross-origin chat, host, nested region, business iframe and greeting wheel routing, with and without popovers.')
} finally { await browser.close() }

