import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.OPEN_CALL_TEST_URL || 'http://127.0.0.1:15273'
const output = path.resolve('node_modules/.cache/agent-open-call')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
await page.addInitScript(() => localStorage.setItem('access_token', 'open-call-ui-test'))
const errors = []
page.setDefaultTimeout(10000)
page.on('pageerror', error => errors.push(error.message))
const key = 'a'.repeat(43)
const config = {
  enabled: false, query_enabled: true,
  path: '/aihub/api/open/agents/99/runs',
}
const writes = []
const runId = 'e'.repeat(32)
let runStatus = 'running'
let recordReads = 0
let failToggle = false
const requests = []
const agents = [
  { id: 99, name: '测试专家', kind: 'expert', can_edit: true },
  { id: 100, name: '未开启调用的专家', kind: 'expert', can_edit: true },
  { id: 101, name: '其他人的专家', kind: 'expert', can_edit: false },
  { id: 1, name: '默认助手', kind: 'personal_default', can_edit: true },
].map(agent => ({ ...agent, icon: 'H', runtime_type: 'claude_code', models: [], skills: [], mcps: [],
  prompt_templates: [], skill_ids: [], mcp_ids: [], prompt_template_ids: [] }))
const record = () => ({
  run_id: runId, status: runStatus, prompt: 'test API question', skill: null,
  created_at: '2026-11-20T08:39:25Z', started_at: '2026-11-20T08:39:28Z',
  finished_at: runStatus === 'succeeded' ? '2026-11-20T08:39:48Z' : null,
  duration_ms: 0, total_tokens: 0, charged_points: '0.00',
  result: runStatus === 'succeeded' ? 'test API result' : null,
  error_code: null, error_message: null,
})
await page.route('**/*', async route => {
  const method = route.request().method()
  const url = new URL(route.request().url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  requests.push(method + ' ' + url.pathname)
  let body = { items: [], total: 0 }
  if (!url.pathname.startsWith('/aihub/api/agents/99/open-call')) {
    if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
    else if (url.pathname === '/aihub/api/agents') body = { items: agents.slice(0, 2), total: 2 }
    else if (url.pathname === '/aihub/api/public/agents') body = { items: [agents[2]], total: 1 }
    else if (/\/agents\/\d+$/.test(url.pathname)) body = agents.find(agent => agent.id === Number(url.pathname.split('/').at(-1)))
    else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant: agents[3] }
    else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
    else if (url.pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
    else if (url.pathname.endsWith('/statistics')) body = { summary: {}, trend: [], sources: [], recent_runs: [], models: [] }
    else if (url.pathname === '/aihub/api/agents/100/open-call') body = { ...config, enabled: false }
    return route.fulfill({ json: body })
  }
  if (url.pathname.includes('/open-call/runs')) {
    if (url.pathname.endsWith('/' + runId)) return route.fulfill({ json: record() })
    recordReads++
    return route.fulfill({ json: { total: url.searchParams.get('run_id') === 'not-found' ? 0 : 1, items: url.searchParams.get('run_id') === 'not-found' ? [] : [record()] } })
  }
  if (method === 'PUT') {
    const data = route.request().postDataJSON()
    if (failToggle) {
      failToggle = false
      return route.fulfill({ status: 409, json: { detail: 'test update failed' } })
    }
    writes.push(data)
    const issue = data.enabled && !config.enabled
    Object.assign(config, data)
    return route.fulfill({ json: { ...config, ...(issue ? { session_key: key } : {}) } })
  }
  if (method === 'POST') return route.fulfill({ json: { ...config, session_key: 'b'.repeat(43) } })
  return route.fulfill({ json: config })
})
try {
  await page.goto(base + '/admin/agents/99')
  const card = page.locator('.open-call')
  const sidebar = page.locator('.expert-workspace > .agent-workspace-nav')
  const recordsMenu = sidebar.getByRole('button', { name: 'API 调用记录', exact: true })
  const settingsMenu = sidebar.getByRole('button', { name: '开放调用', exact: true })
  await settingsMenu.waitFor()
  assert.equal(await card.count(), 0, 'Basic information must not contain open-call settings')
  await settingsMenu.click()
  await page.waitForURL('**/admin/agents/99/open-call')
  assert.equal(await settingsMenu.getAttribute('aria-current'), 'page')
  assert.equal(await page.getByRole('button', { name: '保存', exact: true }).count(), 0)
  await card.getByText('已关闭', { exact: true }).waitFor()
  assert.equal(await recordsMenu.count(), 0)
  assert.equal(await page.getByRole('region', { name: 'API 调用记录' }).count(), 0)
  await card.locator('.el-switch').click()
  await card.getByText('已开启', { exact: true }).waitFor()
  await recordsMenu.waitFor()
  assert.deepEqual((await sidebar.locator('nav button').allTextContents()).slice(-2), ['统计信息', 'API 调用记录'])
  assert.equal(writes.length, 1)
  assert.deepEqual(writes[0], { enabled: true })
  assert.equal(await card.locator('textarea, .el-select').count(), 0)
  for (const label of ['默认提示词', '允许调用的技能', '只读连接器']) {
    assert.equal(await card.getByText(label, { exact: true }).count(), 0)
  }
  assert.equal(await card.getByRole('button', { name: '保存开放调用设置' }).count(), 0)
  assert((await card.innerText()).includes('自动使用智能体已保存的主提示词、技能和连接器'))
  const example = await card.locator('pre').innerText()
  assert(example.includes('X-Agent-Key: ' + key))
  assert(!example.includes('"skill"'))
  assert(example.includes(' \\\n'))
  assert(await card.locator('code').last().innerText().then(value => value.includes('session_key=' + key)))
  await card.screenshot({ path: path.join(output, 'enabled.png') })
  await recordsMenu.click()
  await page.waitForURL('**/admin/agents/99/api-calls')
  assert(await recordsMenu.evaluate(el => el.classList.contains('is-active')))
  assert.equal(await card.count(), 0)
  const records = page.getByRole('region', { name: 'API 调用记录' })
  await records.getByText('执行中', { exact: true }).waitFor()
  await records.getByRole('button', { name: '查看详情' }).click()
  const drawer = page.locator('.el-drawer')
  await drawer.getByText('test API question', { exact: true }).waitFor()
  assert((await drawer.innerText()).includes('0.0 秒'))
  runStatus = 'succeeded'
  await drawer.getByText('test API result', { exact: true }).waitFor({ timeout: 8000 })
  await records.getByText('成功', { exact: true }).waitFor()
  assert(recordReads >= 2)
  await drawer.getByRole('button', { name: /close|关闭/i }).click()
  await records.getByRole('textbox', { name: '按运行 ID 查询' }).fill('not-found')
  await records.getByRole('button', { name: '查询', exact: true }).click()
  await records.locator('.el-table__empty-text').getByText('无', { exact: true }).waitFor()
  await records.getByRole('textbox', { name: '按运行 ID 查询' }).fill(runId)
  await records.getByRole('button', { name: '查询', exact: true }).click()
  await records.getByText('test API question', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(output, 'records.png') })
  await settingsMenu.click()
  await card.getByText('已配置', { exact: true }).waitFor()
  await page.reload()
  await card.getByText('已开启', { exact: true }).waitFor()
  await card.getByText('已配置', { exact: true }).waitFor()
  await recordsMenu.waitFor()
  await card.screenshot({ path: path.join(output, 'configured.png') })
  assert.equal(await card.getByRole('textbox', { name: '本次生成的调用密钥' }).count(), 0)
  assert((await card.locator('pre').innerText()).includes('<已保存的密钥>'))
  await card.getByRole('button', { name: '重置密钥', exact: true }).click()
  await page.locator('.el-message-box').getByRole('button', { name: /确定|确认|OK/ }).click()
  await page.waitForFunction(() => document.querySelector('.open-call pre')?.textContent.includes('b'.repeat(43)))
  failToggle = true
  await card.locator('.el-switch').click()
  await page.getByText('test update failed', { exact: true }).waitFor()
  assert.equal(await card.getByText('已开启', { exact: true }).count(), 1)
  assert.equal(await recordsMenu.count(), 1)
  await card.locator('.el-switch').click()
  await card.getByText('已关闭', { exact: true }).waitFor()
  assert.equal(await card.locator('pre').count(), 0)
  assert.equal(await recordsMenu.count(), 0)
  assert.equal(await records.count(), 0)
  // Owner history remains available by its URL while the menu is hidden.
  await page.goto(base + '/admin/agents/99/api-calls')
  await records.getByText('test API question', { exact: true }).waitFor()
  assert.equal(await recordsMenu.count(), 0)
  assert.deepEqual(writes, [{ enabled: true }, { enabled: false }])

  // The focused workbench shares the same menu state, including direct entry.
  config.enabled = true
  await page.goto(base + '/admin/workspace/agents/99/api-calls?session=42')
  await page.waitForURL('**/workspace/agents/99/api-calls?session=42')
  const focusedNav = page.getByRole('navigation', { name: '更多', exact: true })
  const openFocusedNav = async () => {
    if (!(await focusedNav.isVisible())) await page.getByRole('button', { name: '更多', exact: true }).click()
    await focusedNav.waitFor()
  }
  await openFocusedNav()
  assert.equal(await focusedNav.getByRole('link', { name: 'API 调用记录', exact: true }).count(), 0)
  assert.equal(await focusedNav.getByRole('link', { name: '开放调用', exact: true }).count(), 0)
  assert.deepEqual(await focusedNav.locator('a').allTextContents(), ['渠道配置', '统计信息'])
  await records.getByText('test API question', { exact: true }).waitFor()
  await page.reload()
  await openFocusedNav()
  assert.equal(await focusedNav.getByRole('link', { name: '开放调用', exact: true }).count(), 0)
  await page.goto(base + '/workspace/agents/99/open-call?agent=99&session=42')
  await page.waitForURL('**/workspace/agents/99/open-call?agent=99&session=42')
  await card.getByText('已配置', { exact: true }).waitFor()
  await card.locator('.el-switch').click()
  await card.getByText('已关闭', { exact: true }).waitFor()
  await openFocusedNav()
  assert.equal(await focusedNav.getByRole('link', { name: 'API 调用记录', exact: true }).count(), 0)
  await page.keyboard.press('Escape')
  await focusedNav.waitFor({ state: 'hidden' })
  await card.locator('.el-switch').click()
  await card.getByText('已开启', { exact: true }).waitFor()
  await page.goto(base + '/workspace/agents/99/api-calls?agent=99&session=42')
  await page.waitForURL('**/workspace/agents/99/api-calls?agent=99&session=42')
  await records.getByText('test API question', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(output, 'focused-records.png') })

  // Switching scope must not carry the previous expert's enabled menu.
  await page.goto(base + '/workspace/agents/99/open-call?agent=99&session=42')
  await card.getByText('已配置', { exact: true }).waitFor()
  await page.getByRole('button', { name: '召唤智能体', exact: true }).click()
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/agents/100/open-call')),
    page.getByRole('option', { name: '未开启调用的专家', exact: true }).click(),
  ])
  await page.waitForURL('**/workspace/chat?agent=100')
  await openFocusedNav()
  assert.equal(await focusedNav.getByRole('link', { name: 'API 调用记录', exact: true }).count(), 0)
  await page.goto(base + '/workspace/agents/101/api-calls')
  await page.getByText('仅智能体创建者可查看 API 调用记录', { exact: true }).waitFor()
  await openFocusedNav()
  assert.equal(await focusedNav.getByRole('link', { name: 'API 调用记录', exact: true }).count(), 0)
  assert.equal(await records.count(), 0)
  assert.equal(await focusedNav.getByRole('link', { name: '开放调用', exact: true }).count(), 0)
  await page.goto(base + '/workspace/agents/101/open-call')
  await page.getByText('仅智能体创建者可配置开放调用', { exact: true }).waitFor()
  assert.equal(await card.count(), 0)
  await page.goto(base + '/admin/agents/101/open-call')
  await page.getByText('仅智能体创建者可配置开放调用', { exact: true }).waitFor()
  assert.equal(await settingsMenu.count(), 0)
  assert.equal(requests.some(value => value.includes('/agents/101/open-call')), false)
  await page.goto(base + '/admin/chat')
  await page.locator('.workspace-heading').getByText('默认助手', { exact: true }).waitFor()
  await openFocusedNav()
  assert.equal(await focusedNav.getByRole('link', { name: '开放调用', exact: true }).count(), 0)
  assert.equal(requests.some(value => value.includes('/agents/1/open-call')), false)
  await page.goto(base + '/workspace/agents/99')
  await page.getByRole('button', { name: '保存', exact: true }).waitFor()
  assert.equal(await card.count(), 0, 'Workbench basic information must not contain open-call settings')
  assert.deepEqual(errors, [])
  console.log('Open-call browser checks passed: standalone owner settings, hidden workbench management entries, direct routes/reload/switching, configured key state, key rotation, failed-toggle recovery, records/search, automatic result refresh and retained history.')
} finally {
  await browser.close()
}
