import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const model = { id: 1, name: '测试模型', scope: 'platform', api_protocol: 'anthropic-messages' }
const assistant = { id: 1, name: '测试助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code',
  default_model_id: 1, models: [model], skills: [] }
const credit = { claimed_today: true, available_balance: 100, display_name: '趣点' }

async function scenario(kind) {
  const context = await browser.newContext({ viewport: { width: kind === 'network' ? 390 : 1440, height: 960 } })
  const page = await context.newPage()
  page.setDefaultTimeout(40000)
  let calls = 0
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('access_token', 'bootstrap-test-only'))
  await page.route('**/*', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
    let body = { items: [], total: 0 }
    if (pathname === '/iam/api/me') body = { id: 7, username: 'test', is_superuser: true, permissions: [] }
    else if (pathname.endsWith('/bootstrap')) {
      calls++
      if (calls === 1) {
        if (kind === 'network') return route.abort('failed')
        if (kind === 'missing-settings') return route.fulfill({ status: 409, json: {
          detail: { message: '管理员尚未发布智能体设置', data: { code: 'ASSISTANT_SETTINGS_NOT_PUBLISHED' } },
        } })
        if (kind === 'invalid-response') return route.fulfill({ json: {} })
        if (kind === 'timeout') {
          // Keep the first request pending; the real Axios timeout must finish it.
          await new Promise(resolve => page.once('close', resolve))
          return
        }
        if (kind === 'slow-success') await new Promise(resolve => setTimeout(resolve, 12000))
      }
      body = { assistant_id: 1, assistant, credit }
    } else if (pathname.endsWith('/credits/me')) body = credit
    else if (pathname === '/aihub/api/agents/1') body = assistant
    else if (pathname.endsWith('/models')) body = { items: [model], total: 1 }
    else if (pathname.endsWith('/runtime-status')) body = { status: 'ready' }
    return route.fulfill({ json: body })
  })
  try {
    await page.goto(base + '/workspace/chat')
    const failure = page.locator('.bootstrap-page')
    if (kind === 'slow-success') {
      await page.getByText('正在准备工作台，首次加载或网络较慢时可能需要一点时间…').waitFor()
      await page.locator('.agent-chat-page').waitFor()
      assert.equal(await failure.count(), 0, 'A response after the old 10s timeout must load normally')
    } else {
      await failure.waitFor()
      const expected = {
        network: /无法连接 AI Hub 服务/,
        timeout: /工作台初始化超时/,
        'missing-settings': /管理员尚未发布全局智能体设置/,
        'invalid-response': /默认助手配置无效/,
      }[kind]
      assert.match(await failure.innerText(), expected)
      assert.equal(await failure.getByRole('button', { name: /设置/ }).count(), kind === 'missing-settings' ? 1 : 0)
      assert.equal(calls, 1, 'Initialization must never retry POSTs automatically')
      await failure.getByRole('button', { name: '重试', exact: true }).dblclick()
      await page.locator('.agent-chat-page').waitFor()
      assert.equal(calls, 2, 'Repeated clicks must share one pending initialization')
    }
    assert.equal(await page.locator('.bootstrap-progress').count(), 0)
    assert.deepEqual(errors, [])
    console.log(`Passed: ${kind}`)
  } finally { await context.close() }
}

try {
  await Promise.all(['slow-success', 'timeout', 'network', 'missing-settings', 'invalid-response'].map(scenario))
} finally { await browser.close() }
