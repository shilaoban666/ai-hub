import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.EMBED_TEST_URL || 'http://localhost:15173'
const host = 'http://localhost:10925'
const output = path.resolve('node_modules/.cache/embed-clipboard')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const results = []

try {
  for (const mode of ['allowed', 'denied', 'unavailable', 'failed']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const page = await context.newPage()
    const errors = []
    const failedRequests = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('requestfailed', request => failedRequests.push({ url: request.url(), error: request.failure()?.errorText }))
    await context.addInitScript(mode => {
      if (window === window.top) return
      if (mode === 'unavailable' || mode === 'failed') {
        Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
      }
      if (mode === 'failed') document.execCommand = () => false
    }, mode)
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin === host && url.pathname === '/') {
        return route.fulfill({
          contentType: 'text/html',
          headers: mode === 'denied' ? { 'Permissions-Policy': 'clipboard-write=()' } : {},
          body: `<!doctype html><html><head><meta charset="utf-8"><title>FancyQube clipboard check</title></head><body><textarea id="paste" aria-label="Clipboard verification"></textarea><script src="${base}/embed/assistant.js"></script></body></html>`,
        })
      }
      if (url.pathname === '/func_process_app/aihub_embed_auth/') {
        const request = route.request().postDataJSON()
        return route.fulfill({ json: { code: 0, data: {
          user_id: 7, session_id: 'a'.repeat(64),
          ...(request.action === 'authorize' ? { access_token: 'embed-test-only', token_type: 'bearer', expires_in: 900 } : {}),
        } } })
      }
      // Fulfill dev assets through Playwright so local-network browser policy
      // does not interfere with the synthetic business host.
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) {
        return route.fulfill({ response: await route.fetch() })
      }
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'embed-test', permissions: [] }
      if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
      if (url.pathname === '/aihub/api/agents/1') body = {
        id: 1, name: 'AI assistant', kind: 'personal_default', runtime_type: 'claude_code',
        default_model_id: 1, models: [{ id: 1, name: 'Test model' }], skills: [],
      }
      if (url.pathname === '/aihub/api/agents/1/sessions') body = { total: 1, items: [{ id: 3, title: 'Clipboard session', message_count: 0, model_id: 1 }] }
      if (url.pathname.endsWith('/share')) body = { token: 'browser-share-test' }
      return route.fulfill({ json: body })
    })

    try {
      await page.goto(host)
      await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
      const frameElement = page.locator('iframe[title="AI Hub 对话"]')
      assert.equal(await frameElement.getAttribute('allow'), 'clipboard-write')
      const chat = page.frameLocator('iframe[title="AI Hub 对话"]')
      await chat.getByPlaceholder('输入问题或任务').waitFor()
      await chat.getByRole('button', { name: '打开会话列表', exact: true }).click()
      await chat.getByText('Clipboard session', { exact: true }).last().click()
      await chat.getByRole('button', { name: '查看分享设置', exact: true }).click()
      const dialog = chat.getByRole('dialog', { name: '分享对话' })
      await dialog.waitFor()
      const expected = await dialog.locator('input').inputValue()
      assert.equal(expected, `${base}/share/browser-share-test`)
      for (const label of ['复制链接', '复制分享链接']) {
        await dialog.getByRole('button', { name: label, exact: true }).click()
        if (mode === 'failed') {
          await chat.getByText('复制失败，请手动复制链接', { exact: true }).last().waitFor()
          assert.equal(await chat.getByText('分享链接已复制', { exact: true }).count(), 0)
        } else {
          await chat.getByText('分享链接已复制', { exact: true }).last().waitFor()
          await page.locator('#paste').fill('')
          await page.locator('#paste').press('Control+V')
          assert.equal(await page.locator('#paste').inputValue(), expected, `${mode}: ${label} must write the real clipboard`)
        }
        assert.equal(await dialog.locator('textarea').count(), 0, 'Temporary selection must be removed')
      }
      if (mode === 'denied') {
        await page.setViewportSize({ width: 390, height: 844 })
        await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
        await dialog.getByRole('button', { name: '复制链接', exact: true }).click()
        await chat.getByText('分享链接已复制', { exact: true }).last().waitFor()
        assert(await dialog.evaluate(element => {
          const bounds = element.getBoundingClientRect()
          return bounds.left >= 0 && bounds.right <= innerWidth
        }))
        await page.screenshot({ path: path.join(output, 'share-mobile.png') })
      }
      assert.deepEqual(errors, [])
      results.push({ mode, passed: true })
    } catch (error) {
      await page.screenshot({ path: path.join(output, `${mode}-failure.png`) })
      process.stderr.write(`${JSON.stringify({ mode, errors, failedRequests, frames: page.frames().map(frame => frame.url()) })}\n`)
      throw error
    } finally {
      await context.close()
    }
  }
  process.stdout.write(`${JSON.stringify(results, null, 2)}\n`)
} finally {
  await browser.close()
}
