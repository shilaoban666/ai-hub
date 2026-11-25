import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const errors = []
const model = { id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'platform' }
const assistant = { id: 1, name: '默认助手', kind: 'personal_default', runtime_type: 'claude_code', models: [model], default_model_id: 1 }

async function setup({ height = 1200, total = 100, failure = false, empty = false, collapsed = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height } })
  const offsets = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(collapsed => {
    localStorage.setItem('access_token', 'history-pagination-test')
    localStorage.setItem('aihub:sidebar-collapsed', String(collapsed))
  }, collapsed)
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
    let body = { items: [], total: 0 }
    if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
    else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
    else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 0 }
    else if (/\/agents\/1$/.test(url.pathname)) body = assistant
    else if (url.pathname.endsWith('/sessions')) {
      const skip = Number(url.searchParams.get('skip'))
      const limit = Number(url.searchParams.get('limit'))
      offsets.push(skip)
      if (skip && failure) return route.fulfill({ status: 500, json: { detail: '模拟分页失败' } })
      const count = skip && empty ? 0 : Math.max(0, Math.min(limit, total - skip))
      body = { total, items: Array.from({ length: count }, (_, i) => ({
        id: skip + i + 1, title: `历史对话 ${skip + i + 1}`, source: 'web', message_count: 1,
        created_at: '2026-11-01T00:00:00Z',
      })) }
    } else if (url.pathname.endsWith('/models')) body = { items: [model], total: 1 }
    else if (url.pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
    else if (url.pathname.endsWith('/files')) body = { files: [] }
    await route.fulfill({ json: body })
  })
  await page.goto(base + '/workspace/chat')
  await page.waitForFunction(() => document.querySelectorAll('#workspace-history .session-item').length >= 20)
  return { page, offsets }
}

const waitForRows = (page, count) => page.waitForFunction(count => document.querySelectorAll('#workspace-history .session-item').length === count, count)
const scrollToBottom = page => page.locator('#workspace-history .session-list').evaluate(el => { el.scrollTop = el.scrollHeight })

try {
  // A tall viewport fits the first page entirely: loading must proceed without a scroll event.
  const tall = await setup()
  await waitForRows(tall.page, 40)
  assert.deepEqual(tall.offsets, [0, 20])
  assert.equal(await tall.page.locator('#workspace-history .session-list').evaluate(el => el.scrollHeight > el.clientHeight), true)
  await scrollToBottom(tall.page)
  await waitForRows(tall.page, 60)
  assert.deepEqual(tall.offsets, [0, 20, 40])
  await tall.page.close()

  // Enlarging the window can remove overflow after the initial page was already loaded.
  const resized = await setup({ height: 700, total: 45 })
  assert.deepEqual(resized.offsets, [0])
  await resized.page.setViewportSize({ width: 1440, height: 2200 })
  await waitForRows(resized.page, 45)
  await resized.page.waitForTimeout(350)
  assert.deepEqual(resized.offsets, [0, 20, 40])
  await resized.page.close()

  // Hidden history must not drain pages; opening it should fill the available area.
  const hidden = await setup({ collapsed: true })
  await hidden.page.waitForTimeout(350)
  assert.deepEqual(hidden.offsets, [0])
  await hidden.page.getByRole('button', { name: '展开主菜单' }).click()
  await waitForRows(hidden.page, 40)
  assert.deepEqual(hidden.offsets, [0, 20])
  await hidden.page.close()

  // Failure and an empty page with a stale total must not cause automatic retry loops.
  for (const options of [{ failure: true }, { empty: true }]) {
    const stalled = await setup(options)
    await stalled.page.waitForFunction(() => document.querySelector('#workspace-history .session-list')?.getAttribute('aria-busy') === 'false')
    await stalled.page.waitForTimeout(700)
    assert.deepEqual(stalled.offsets, [0, 20])
    assert.equal(await stalled.page.locator('#workspace-history .session-item').count(), 20)
    await stalled.page.close()
  }
  assert.deepEqual(errors, [])
  console.log('Passed: viewport autofill, scrolling, resize, expand, exhausted pages, and no retry loop on failed/empty pages.')
} finally {
  await browser.close()
}
