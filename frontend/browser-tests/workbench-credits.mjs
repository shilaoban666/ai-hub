import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
page.setDefaultTimeout(10000)
const errors = []
let claims = 0
let account = { claimed_today: false, available_balance: 0, display_name: '积分' }
const model = { id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'platform' }
const common = { runtime_type: 'claude_code', models: [model], default_model_id: 1, skills: [], prompt_templates: [], mcp_connections: [] }
const assistant = { ...common, id: 1, name: '默认助手', kind: 'personal_default', icon: 'H' }
const expert = { ...common, id: 99, name: '自定义智能体', kind: 'expert', icon: '🚀' }
await page.addInitScript(() => localStorage.setItem('access_token', 'workbench-credit-test-only'))
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request(), pathname = new URL(request.url()).pathname
  if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
  let body = { items: [], total: 0 }
  if (pathname === '/iam/api/me') body = { id: 7, username: 'tester', permissions: [] }
  else if (pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant, credit: account }
  else if (pathname.endsWith('/credits/me/daily-claim')) {
    assert.equal(request.method(), 'POST')
    claims += 1
    account = { ...account, claimed_today: true, available_balance: 100 }
    body = account
  } else if (pathname.endsWith('/credits/me')) body = account
  else if (pathname === '/aihub/api/agents') body = { items: [expert], total: 1 }
  else if (/\/agents\/\d+$/.test(pathname)) body = pathname.endsWith('/99') ? expert : assistant
  else if (pathname.endsWith('/models')) body = { items: [model], total: 1 }
  else if (pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
  else if (pathname.endsWith('/skills/sync')) body = { status: 'synced' }
  else if (pathname.endsWith('/files')) body = { files: [] }
  await route.fulfill({ json: body })
})
const header = page.locator('.chat-center > .agent-workspace-header:visible')
const claim = () => header.getByRole('button', { name: '领取今日积分', exact: true })
const balance = () => header.getByRole('button', { name: '查看积分余额', exact: true })
const choose = async name => {
  await page.locator('.workspace-heading').getByRole('button', { name: '召唤智能体', exact: true }).click()
  await page.locator('.agent-switcher-popover:visible').getByRole('option', { name, exact: true }).click()
}
try {
  await page.goto(`${base}/workspace/chat`)
  await claim().waitFor()
  assert.equal(await header.locator('.header-tool-dot').count(), 1)
  await choose('自定义智能体')
  await page.waitForURL(`${base}/workspace/chat?agent=99`)
  await claim().waitFor()
  assert.equal(await header.locator('.header-tool-dot').count(), 1)
  await claim().click()
  await balance().waitFor()
  assert.equal(claims, 1)
  assert.equal(await header.locator('.header-tool-dot').count(), 0)
  await balance().click()
  assert.equal(claims, 1, 'An already claimed account must not claim again')
  await choose('默认助手')
  await page.waitForURL(`${base}/workspace/chat`)
  await balance().waitFor()
  await choose('自定义智能体')
  await page.waitForURL(`${base}/workspace/chat?agent=99`)
  await balance().waitFor()
  await page.reload()
  await balance().waitFor()
  // Account updates from other views must also reach the summoned agent header.
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('aihub:credit-account-updated', {
    detail: { claimed_today: true, available_balance: 250, display_name: '趣点' },
  })))
  await header.getByRole('button', { name: '查看趣点余额', exact: true }).waitFor()
  account = { claimed_today: false, available_balance: 0, display_name: '积分' }
  await page.reload()
  await claim().waitFor()
  assert.equal(await header.locator('.header-tool-dot').count(), 1)
  await claim().click()
  await balance().waitFor()
  assert.equal(claims, 2, 'Opening a custom agent directly must support claiming')
  assert.deepEqual(errors, [])
  console.log('Passed: default/custom header entry; claim from summoned and directly opened agents; claimed state after switching/reload; account update events; zero balance; no page errors.')
} finally {
  await browser.close()
}
