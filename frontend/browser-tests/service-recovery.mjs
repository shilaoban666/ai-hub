import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const output = path.resolve('../output/playwright/service-recovery')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
try {
  for (const [failure, viewport] of [
    ['json-503', { width: 1440, height: 960 }],
    ['html-502', { width: 390, height: 844 }],
    ['network', { width: 1440, height: 960 }],
  ]) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    page.setDefaultTimeout(10000)
    let available = false
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/aihub/api/**', route => {
      if (!available) {
        if (failure === 'network') return route.abort('failed')
        if (failure === 'html-502') return route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>Bad Gateway</h1>' })
        return route.fulfill({ status: 503, json: { code: 503, message: 'Service temporarily unavailable', timestamp: '2026-11-03', data: null } })
      }
      const list = new URL(route.request().url()).pathname === '/aihub/api/public/skills'
      return route.fulfill({ json: list ? { total: 1, items: [{ id: 7, name: '服务恢复测试技能', description: '数据已自动恢复', author: '测试', tags: [], modules: [], roles: [] }] } : { items: [], modules: [], roles: [] } })
    })
    try {
      await page.goto(`${base}/skills`)
      const notice = page.locator('.service-availability-notice')
      await notice.waitFor()
      assert.equal(await notice.count(), 1)
      await page.evaluate(() => { window.__serviceRecoveryDocument = 'original-document' })
      const search = page.getByPlaceholder('搜索技能名称、作者或适用角色')
      await search.fill('保留中的搜索')
      assert.equal(await page.locator('.el-message--error').count(), 0)
      await page.screenshot({ path: path.join(output, `${failure}-reconnecting.png`) })
      const bounds = await notice.boundingBox()
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width)
      available = true
      if (failure === 'html-502') await notice.getByRole('button', { name: '立即重试' }).click()
      await page.getByText('服务恢复测试技能', { exact: true }).waitFor()
      await notice.waitFor({ state: 'hidden' })
      assert.equal(await search.inputValue(), '保留中的搜索')
      assert.equal(await page.evaluate(() => window.__serviceRecoveryDocument), 'original-document')
      assert.equal(await page.locator('.el-message--error').count(), 0)
      assert.deepEqual(errors, [])
    } finally { await context.close() }
  }
  const page = await browser.newPage()
  await page.route('**/aihub/api/**', route => route.fulfill({ status: 503,
    headers: { 'x-aihub-error': 'business' }, json: { code: 503, message: '模型当前不可用', timestamp: '2026-11-03', data: null },
  }))
  await page.goto(`${base}/skills`)
  await page.locator('.el-message--error').first().waitFor()
  assert.equal(await page.locator('.service-availability-notice').count(), 0)
  await page.close()
  console.log('Browser checks passed: JSON 503, HTML 502, network loss, desktop/mobile notice, automatic data recovery, retained search, no reload, business 503 bypass.')
} finally { await browser.close() }
