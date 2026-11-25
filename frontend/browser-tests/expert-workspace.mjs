import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'expert-workspace-test'))
const page = await context.newPage()
page.setDefaultTimeout(15000)
const errors = []
const requests = []
const mutations = []
const statusUpdates = []
const authUpdates = []
const promptInstalls = []
let mcpBound = true
const mcp = { id: 501, definition_id: 601, name: '测试连接器', transport_type: 'streamable_http', status: 'active', auth_mode: 'manual', is_system: false }
const pending = new Map()
const hold = path => {
  let release
  const promise = new Promise(resolve => { release = resolve })
  pending.set(path, promise)
  return () => { pending.delete(path); release() }
}
page.on('pageerror', error => errors.push(error.message))
const agent = { id: 99, name: '测试专家', icon: '🧠', kind: 'expert', runtime_type: 'claude_code',
  models: [], skills: [], mcps: [], prompt_templates: [{ id: 701, name: '测试提示词', category: '其他', content: '提示词内容' }], skill_ids: [], mcp_ids: [], prompt_template_ids: [701] }
const promptCatalog = [
  { ...agent.prompt_templates[0], origins: ['mine'] },
  { id: 702, name: '公开摘要', author: ' ', content: '整理要点', origins: ['public'] },
]
const sessions = Array.from({ length: 55 }, (_, i) => ({ id: i + 1, title: `历史测试 ${i + 1}`,
  message_count: 2, source: 'web', created_at: '2026-09-28T01:00:00', last_message_at: '2026-09-28T02:00:00' }))
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  requests.push(url.pathname + url.search)
  if (route.request().method() === 'DELETE') mutations.push(url.pathname)
  if (pending.has(url.pathname)) await pending.get(url.pathname)
  let body = { items: [], total: 0 }
  if (url.pathname.endsWith('/me') && url.pathname.includes('/iam/')) body = { id: 7, username: 'tester', permissions: [] }
  else if (url.pathname.endsWith('/assets/mcp/connections/501/status') && route.request().method() === 'PUT') {
    const data = route.request().postDataJSON()
    statusUpdates.push(data)
    mcp.status = data.status
    body = mcp
  }
  else if (url.pathname.endsWith('/assets/mcp/connections/501/headers')) {
    if (route.request().method() === 'PUT') {
      const data = route.request().postDataJSON()
      authUpdates.push(data)
      mcp.auth_mode = data.auth_mode
    } else {
      assert.equal(url.searchParams.get('agent_id'), '99')
    }
    body = { auth_mode: mcp.auth_mode, headers: [] }
  }
  else if (url.pathname.endsWith('/assets/mcp/connections')) body = { items: mcpBound ? [mcp] : [], total: mcpBound ? 1 : 0 }
  else if (url.pathname.endsWith('/assets/prompts/catalog')) {
    assert.equal(url.searchParams.get('agent_id'), '99')
    const source = url.searchParams.get('source')
    const items = promptCatalog.map(prompt => ({ ...prompt, installed: agent.prompt_template_ids.includes(prompt.id) }))
      .filter(prompt => url.searchParams.get('installed_only') !== 'true' || prompt.installed)
      .filter(prompt => source === 'all' || prompt.origins.includes(source))
    body = { items, total: items.length }
  }
  else if (url.pathname.endsWith('/assets/prompts/import') && route.request().method() === 'POST') {
    const data = route.request().postDataJSON()
    promptInstalls.push(data)
    agent.prompt_template_ids.push(data.source_template_id)
    body = promptCatalog.find(row => row.id === data.source_template_id)
    agent.prompt_templates.push(body)
  }
  else if (url.pathname.endsWith('/assets/prompts/701/bindings/99') && route.request().method() === 'DELETE') {
    agent.prompt_templates = []
    agent.prompt_template_ids = []
    body = { status: 'unbound' }
  }
  else if (url.pathname.endsWith('/assets/mcp/connections/501/bindings/99') && route.request().method() === 'DELETE') {
    mcpBound = false
    body = { status: 'unbound', removed: true }
  }
  else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant: { ...agent, id: 1, name: '默认助手', kind: 'personal_default' } }
  else if (url.pathname.endsWith('/agents')) body = { items: [agent], total: 1 }
  else if (url.pathname.endsWith('/agents/99')) body = agent
  else if (url.pathname.endsWith('/agents/99/sessions')) {
    const skip = Number(url.searchParams.get('skip') || 0)
    const limit = Number(url.searchParams.get('limit') || 20)
    body = { items: sessions.slice(skip, skip + limit), total: sessions.length }
  } else if (/\/sessions\/\d+\/messages$/.test(url.pathname)) {
    body = { items: [], has_more: false, session: sessions[0] }
  } else if (url.pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
  else if (url.pathname.includes('/channels/')) body = { enabled: false, status: 'unbound' }
  else if (url.pathname.endsWith('/statistics')) body = { summary: {}, trend: [], sources: [], recent_runs: [], models: [] }
  await route.fulfill({ json: body })
})
const base = process.env.EXPERT_TEST_URL || 'http://127.0.0.1:15176'
const sidebar = page.locator('.expert-workspace > .agent-workspace-nav')
const ready = () => page.waitForFunction(() => ![...document.querySelectorAll('.el-loading-mask')].some(el => getComputedStyle(el).display !== 'none'))
try {
  // Direct resource entry loads configuration identity without initializing chat.
  const releaseSkills = hold('/aihub/api/assets/skills/catalog')
  await page.goto(`${base}/admin/agents/99?section=skills`)
  await sidebar.getByText(agent.name, { exact: true }).waitFor()
  assert.deepEqual(await sidebar.getByRole('group').evaluateAll(nodes => nodes.map(node => node.getAttribute('aria-label'))), ['智能体设置', '能力资源', '运行记录'])
  assert.equal(await page.locator('.chat-sidebar, .agent-chat-page').count(), 0)
  await page.locator('.skill-grid > .el-loading-mask').waitFor({ state: 'visible' })
  assert.equal(await page.locator('.expert-workspace-content .el-loading-mask:visible').count(), 1, 'Only the skill list should show loading')
  assert.equal(await page.getByRole('button', { name: '保存', exact: true }).count(), 0, 'Resources should not expose the basic editor save action')
  assert.equal(requests.some(url => /^\/aihub\/api\/(models|public\/skills|public\/mcps)(\?|$)/.test(url)), false, 'Resource entry must not fetch the basic editor')
  await mkdir('../output/playwright', { recursive: true })
  await page.screenshot({ path: '../output/playwright/expert-workspace-loading.png' })
  releaseSkills()
  await ready()
  const catalogRequests = () => requests.filter(url => url.includes('/assets/skills/catalog?')).length
  const beforeRefresh = catalogRequests()
  await Promise.all([
    page.waitForResponse(response => response.url().includes('/assets/skills/catalog?')),
    page.getByRole('button', { name: '刷新资源', exact: true }).click(),
  ])
  await ready()
  assert.equal(catalogRequests(), beforeRefresh + 1, 'Skill refresh must reload the skill catalog')

  // A pending basic editor request must not cover the resource opened next.
  const releaseModels = hold('/aihub/api/models')
  await sidebar.getByRole('button', { name: '基本信息', exact: true }).click()
  await page.locator('.agent-detail > .el-loading-mask').waitFor({ state: 'visible' })
  const releaseMcp = hold('/aihub/api/assets/mcp/connections')
  await sidebar.getByRole('button', { name: '连接器', exact: true }).click()
  await page.locator('.connector-grid > .el-loading-mask').waitFor({ state: 'attached' })
  await page.locator('.agent-detail > .el-loading-mask').waitFor({ state: 'hidden' })
  assert.equal(await page.locator('.expert-workspace-content > .el-loading-mask:visible').count(), 0, 'Pending basic editor must not mask MCP list')
  releaseModels()
  releaseMcp()
  await ready()

  // Enable/disable actions carry the current agent scope and survive a refresh.
  const table = page.locator('.connector-grid')
  await table.getByRole('button', { name: '认证配置', exact: true }).click()
  const authDialog = page.locator('.mcp-auth-dialog')
  await authDialog.getByText('不发送认证', { exact: true }).click()
  await authDialog.getByRole('button', { name: '保存配置', exact: true }).click()
  await authDialog.waitFor({ state: 'hidden' })
  assert.deepEqual(authUpdates, [{ headers: {}, auth_mode: 'none', inherit_system: false, agent_id: 99 }])
  const connectionSwitch = table.locator('.el-switch__core')
  await connectionSwitch.click()
  await table.getByRole('switch', { name: '启用 测试连接器', checked: false }).waitFor({ state: 'attached' })
  await page.getByRole('button', { name: '刷新资源', exact: true }).click()
  await ready()
  await connectionSwitch.click()
  await table.getByRole('switch', { name: '启用 测试连接器', checked: true }).waitFor({ state: 'attached' })
  assert.deepEqual(statusUpdates, [{ status: 'disabled', agent_id: 99 }, { status: 'active', agent_id: 99 }])
  await page.screenshot({ path: '../output/playwright/expert-workspace-mcp-actions.png' })

  // Cancelling a connection only removes the current agent binding.
  const deleteButton = page.locator('.connector-grid').getByRole('button', { name: '取消连接', exact: true })
  await deleteButton.waitFor()
  assert.equal(await deleteButton.evaluate(el => el.classList.contains('el-button--danger')), true)
  assert.equal(await page.getByRole('button', { name: '卸载', exact: true }).count(), 0)
  await deleteButton.click()
  const confirmation = page.locator('.el-message-box')
  await confirmation.getByRole('button', { name: '取消', exact: true }).click()
  assert.deepEqual(mutations, [], 'Cancel must not remove a connector')
  await deleteButton.click()
  await confirmation.getByText('取消连接', { exact: true }).waitFor()
  await confirmation.getByRole('button', { name: '确定', exact: true }).click()
  await deleteButton.waitFor({ state: 'hidden' })
  assert.deepEqual(mutations, ['/aihub/api/assets/mcp/connections/501/bindings/99'], 'Delete only the current agent binding')
  await sidebar.getByRole('button', { name: '提示词库', exact: true }).click()
  const promptTable = page.locator('.asset-table')
  const promptScope = page.getByRole('group', { name: '提示词范围' })
  const promptSource = page.getByRole('group', { name: '提示词来源' })
  const publicPrompt = promptTable.getByRole('row').filter({ hasText: '公开摘要' })
  await publicPrompt.getByRole('button', { name: '安装', exact: true }).waitFor()
  assert.equal(await publicPrompt.getByText('无', { exact: true }).count(), 2, 'Blank author and category show 无')
  await promptScope.getByRole('button', { name: '已安装', exact: true }).click()
  await publicPrompt.waitFor({ state: 'hidden' })
  const ownPrompt = promptTable.getByRole('row').filter({ hasText: '测试提示词' })
  const removePrompt = ownPrompt.getByRole('button', { name: '卸载', exact: true })
  await removePrompt.click()
  await confirmation.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(mutations.length, 1, 'Cancel must preserve the prompt binding')
  await removePrompt.click()
  await confirmation.getByRole('button', { name: '确定', exact: true }).click()
  await removePrompt.waitFor({ state: 'hidden' })
  assert.equal(mutations.at(-1), '/aihub/api/assets/prompts/701/bindings/99')
  await promptScope.getByRole('button', { name: '全部', exact: true }).click()
  await ownPrompt.getByRole('button', { name: '安装', exact: true }).waitFor()
  await promptSource.getByRole('button', { name: '公开', exact: true }).click()
  await ownPrompt.waitFor({ state: 'hidden' })
  await publicPrompt.getByRole('button', { name: '安装', exact: true }).click()
  await publicPrompt.getByRole('button', { name: '卸载', exact: true }).waitFor()
  assert.deepEqual(promptInstalls, [{ source_template_id: 702, agent_id: 99 }])
  await promptScope.getByRole('button', { name: '已安装', exact: true }).click()
  await ready()
  await publicPrompt.getByRole('button', { name: '卸载', exact: true }).waitFor()
  const chatRequests = () => requests.filter(url => /\/(sessions|runtime-status|workspace|chat-config)(\?|$)/.test(url))
  assert.deepEqual(chatRequests(), [], 'Configuration must not initialize chat services')
  assert.equal(await sidebar.getByRole('button', { name: '渠道配置', exact: true }).count(), 0)
  for (const name of ['基本信息', '技能市场', '提示词库', '连接器', '统计信息']) {
    await sidebar.getByRole('button', { name, exact: true }).click()
    await ready()
    assert.equal(await page.locator('.chat-sidebar, .agent-chat-page').count(), 0, name)
    assert.equal(await sidebar.getByRole('button', { name, exact: true }).getAttribute('aria-current'), 'page')
  }
  assert.deepEqual(chatRequests(), [], 'Switching configuration menus must not initialize chat services')

  // The configuration stays open while a separate workbench selects this agent.
  const originalUrl = page.url()
  const chatLink = sidebar.getByRole('link', { name: '开始对话（新窗口打开工作台）', exact: true })
  assert.equal(await chatLink.getAttribute('href'), '/workspace/chat?agent=99')
  const [workbench] = await Promise.all([context.waitForEvent('page'), chatLink.click()])
  await workbench.waitForURL('**/workspace/chat?agent=99')
  await workbench.locator('.workspace-sidebar').getByText(agent.name, { exact: true }).waitFor()
  assert.equal(page.url(), originalUrl)
  assert.equal(await workbench.locator('.agent-chat-page').count(), 1)
  await workbench.close()

  // Narrow screens retain the chat action and horizontally scrollable menu.
  await page.setViewportSize({ width: 390, height: 844 })
  await chatLink.waitFor({ state: 'visible' })
  const navBounds = await sidebar.boundingBox()
  const chatBounds = await chatLink.boundingBox()
  assert(navBounds.width <= 390)
  assert(chatBounds.x >= 0 && chatBounds.x + chatBounds.width <= 390)
  assert(await page.locator('.expert-workspace-content').evaluate(el => el.clientHeight > 200))
  await page.screenshot({ path: '../output/playwright/expert-workspace-mobile.png' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  assert.deepEqual(errors, [])
  await mkdir('../output/playwright', { recursive: true })
  await sidebar.getByRole('button', { name: '统计信息', exact: true }).click()
  await ready()
  await page.screenshot({ path: '../output/playwright/expert-workspace-statistics.png' })
  await page.goto(`${base}/admin/agents/99/chat?session=1&agent=100`)
  await page.waitForURL('**/workspace/chat?session=1&agent=99')
  assert.deepEqual(errors, [])
  console.log('PASS: configuration menus, scoped resources, no background chat, new-window workbench selection, mobile layout and legacy chat redirect.')
} catch (error) {
  console.error({ url: page.url(), errors, requests, text: (await page.locator('body').innerText()).slice(0, 1500) })
  throw error
} finally {
  await browser.close()
}
