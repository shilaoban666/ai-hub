import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15177'
const output = path.resolve('node_modules/.cache/composer-layout-focus')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 960 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    let releaseLists
    const listsGate = new Promise(resolve => { releaseLists = resolve })
    let releaseHistory
    const historyGate = new Promise(resolve => { releaseHistory = resolve })
    await page.addInitScript(() => localStorage.setItem('access_token', 'composer-focus-test'))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'test', permissions: [] }
      if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
      if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', kind: 'personal_default', runtime_type: 'claude_code', models: [], skills: [] }
      if (url.pathname.endsWith('/assets/skills/available') || url.pathname.endsWith('/agents/1/sessions')) await listsGate
      if (url.pathname.endsWith('/sessions/3/messages')) {
        await historyGate
        body = { session: { id: 3, source: 'web' }, items: [{ id: 1, role: 'user', content: 'Previous message' }] }
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    const input = page.getByPlaceholder('输入问题或任务')
    const waitForFocus = () => page.waitForFunction(() => document.activeElement?.matches('.cm-content[contenteditable="true"]'), null, { timeout: 5000 })
    const checkHeight = async () => {
      const height = await page.locator('.cm-editor').evaluate(el => el.getBoundingClientRect().height)
      assert.equal(height, width < 400 ? 77 : 98, 'Editor must retain the original textarea height')
    }

    await page.goto(`${base}/embed/chat`)
    await waitForFocus()
    await checkHeight()
    await page.keyboard.insertText('Ready before auxiliary lists finish')
    assert.match(await input.textContent(), /Ready before auxiliary lists finish/)
    await page.getByRole('button', { name: '工作区文件', exact: true }).click()
    const focusedBeforeLists = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'))
    const listsResponse = page.waitForResponse(response => response.url().includes('/assets/skills/available'))
    releaseLists()
    await listsResponse
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), focusedBeforeLists, 'Late auxiliary lists must not steal focus')

    await page.goto(`${base}/embed/chat?session=3`)
    await page.locator('.cm-content[contenteditable="false"]').waitFor()
    assert.equal(await input.evaluate(el => el === document.activeElement), false, 'History loading must keep the editor disabled')
    releaseHistory()
    await waitForFocus()
    await checkHeight()
    await page.reload()
    await waitForFocus()
    await checkHeight()
    await page.keyboard.insertText('Typing immediately after refresh')
    assert.match(await input.textContent(), /Typing immediately after refresh/)
    await page.screenshot({ path: path.join(output, `refreshed-${width}.png`), animations: 'disabled' })
    await page.getByRole('button', { name: '新对话', exact: true }).click()
    await waitForFocus()
    assert.equal(await input.locator('.cm-line').textContent(), '输入问题或任务')
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Composer height and focus passed: desktop/mobile, slow auxiliary lists, history loading, refresh, new conversation.')
} finally {
  await browser.close()
}
