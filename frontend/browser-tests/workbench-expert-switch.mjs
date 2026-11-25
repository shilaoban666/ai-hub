import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15176'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const openResources = async () => {
  await page.getByRole('button', { name: '更多', exact: true }).click()
  await page.getByRole('navigation', { name: '更多', exact: true }).waitFor()
}
const resourceLink = name => page.getByRole('navigation', { name: ['技能市场', '连接器', '提示词库'].includes(name) ? '资源与工具' : '更多', exact: true }).getByRole('link', { name, exact: true })
const chooseResource = async name => {
  if (!['技能市场', '连接器', '提示词库'].includes(name)) await openResources()
  await resourceLink(name).click()
}
page.setDefaultTimeout(12000)
const errors = []
const requests = []
const posts = []
let running = false
let reconnects = 0
let failList = false
let releaseBootstrap
const bootstrapGate = new Promise(resolve => { releaseBootstrap = resolve })
const agents = [
  { id: 1, name: '默认助手', kind: 'personal_default', skills: [] },
  { id: 99, name: '商品合规专家', kind: 'expert', skills: [{ id: 9, name: '合规检查' }] },
  { id: 100, name: '数据分析专家', kind: 'expert', skills: [{ id: 10, name: '数据分析' }] },
].map(agent => ({ ...agent, icon: agent.id === 99 ? '@cow' : agent.id === 100 ? '@sprout' : 'H', runtime_type: 'claude_code', default_model_id: 1,
  models: [{ id: 1, name: '测试模型' }], prompt_templates: [], mcps: [] }))
agents[1].prompt_template_ids = [991]
agents[1].prompt_templates = [{ id: 991, name: '专家独立提示词', content: '专家专用内容', category: '其他' }]
const resourceWrites = []
const expertConnection = { id: 991, name: '专家独立 MCP', transport_type: 'streamable_http', status: 'active', auth_mode: 'manual', is_system: false }
const session = (id, agentId) => ({ id, agent_id: agentId, title: `${agentId} 的历史对话`,
  source: 'web', message_count: 2, model_id: 1, created_at: '2026-10-14T01:00:00',
  ...(id === 990 && running ? { active_run_id: 'expert-run', active_run_status: 'running' } : {}) })
const sessionLists = () => ({
  1: [session(10, 1)],
  99: [{ ...session(999, 99), source: 'dingtalk' }, session(990, 99)],
  100: [],
})
const frame = events => `id: 3\ndata: ${JSON.stringify({ type: 'run_snapshot', revision: 3, events })}\n\n`
const events = [
  { type: 'run_queued', run_id: 'expert-run', session_id: 990, user_content: '检查商品合规' },
  { type: 'run_start', run_id: 'expert-run', session_id: 990 },
  { type: 'text', content: '专家正在检查商品。' },
]
await page.addInitScript(() => {
  localStorage.setItem('access_token', 'workbench-switch-test')
  const original = window.fetch
  window.fetch = async (url, options) => {
    const response = await original(url, options)
    if (!response.headers.get('content-type')?.includes('text/event-stream')) return response
    const initial = await response.text()
    return new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(initial))
        options.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), { once: true })
      },
    }), { headers: response.headers })
  }
})
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request()
  const url = new URL(request.url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  requests.push(`${request.method()} ${url.pathname}${url.search}`)
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
  else if (url.pathname.endsWith('/bootstrap')) {
    await bootstrapGate
    body = { assistant_id: 1, assistant: agents[0] }
  }
  else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100, display_name: '算点' }
  else if (url.pathname === '/aihub/api/agents') {
    if (failList) return route.fulfill({ status: 500, json: { detail: 'test failure' } })
    body = { items: agents.slice(1), total: 2 }
  } else if (/\/agents\/\d+$/.test(url.pathname)) {
    body = agents.find(agent => agent.id === Number(url.pathname.split('/').at(-1)))
    if (request.method() === 'PUT') Object.assign(body, request.postDataJSON())
  }
  else if (/\/agents\/\d+\/sessions$/.test(url.pathname)) {
    const id = Number(url.pathname.split('/').at(-2))
    body = { items: sessionLists()[id] || [], total: (sessionLists()[id] || []).length }
  } else if (/\/sessions\/\d+\/messages$/.test(url.pathname)) {
    const [, agentId, sessionId] = url.pathname.match(/agents\/(\d+)\/sessions\/(\d+)/)
    assert.ok(sessionLists()[agentId].some(item => item.id === Number(sessionId)), 'Session must belong to the requested agent')
    body = { session: sessionLists()[agentId].find(item => item.id === Number(sessionId)), items: [
      { id: Number(sessionId) * 10, role: 'user', content: `${agentId} 的提问` },
      { id: Number(sessionId) * 10 + 1, role: 'assistant', content: JSON.stringify([{ type: 'text', content: `${agentId} 的独立回答` }]) },
    ] }
  } else if (/\/agents\/\d+\/messages$/.test(url.pathname)) {
    posts.push({ path: url.pathname, body: request.postDataJSON() })
    running = true
    return route.fulfill({ contentType: 'text/event-stream', body: frame(events) })
  } else if (url.pathname.endsWith('/runs/expert-run/events')) {
    reconnects++
    return route.fulfill({ contentType: 'text/event-stream', body: frame(events) })
  } else if (url.pathname.endsWith('/files')) body = { files: [{ name: `${url.pathname.includes('/99/') ? '专家' : '默认'}文件.txt`, path: 'report.txt', type: 'file' }] }
  else if (url.pathname.includes('/channels/')) body = { enabled: true, status: 'active', session_id: url.pathname.includes('/agents/1/') ? 10 : 999 }
  else if (url.pathname.endsWith('/statistics')) {
    const days = Number(url.searchParams.get('days') || 7)
    body = {
      days, start_at: '2026-10-08T00:00:00+08:00', end_at: '2026-10-14T14:00:00+08:00', credit_display_name: '趣点',
      summary: { total_runs: days === 1 ? 0 : 4, charged_points: days === 1 ? '0.00' : '14.00' },
      trend: days === 1 ? [{ date: '2026-10-14', charged_points: '0.00' }] : [
        { date: '2026-10-13', charged_points: '4.00' }, { date: '2026-10-14', charged_points: '10.00' },
      ],
      sources: days === 1 ? [] : [
        { source: 'web', total_runs: 3, charged_points: '10.00' },
        { source: 'weixin_clawbot', total_runs: 1, charged_points: '4.00' },
      ],
      recent_runs: [], models: [],
    }
  }
  else if (url.pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
  else if (url.pathname === '/aihub/api/assets/mcp/connections') {
    const items = url.searchParams.get('agent_id') === '99' ? [expertConnection]
      : url.searchParams.has('agent_id') ? []
        : [{ id: -21, definition_id: 21, name: '默认助手系统 MCP', transport_type: 'streamable_http', status: 'active', auth_mode: 'current_user', is_system: true }]
    body = { items, total: items.length }
  } else if (url.pathname === '/aihub/api/assets/mcp/connections/991/status') {
    resourceWrites.push(request.postDataJSON())
    expertConnection.status = request.postDataJSON().status
    body = expertConnection
  } else if (url.pathname === '/aihub/api/assets/prompts') {
    body = { items: [{ id: 21, name: '默认助手系统提示词', content: '默认内容', category: '其他', is_system: true }], total: 1 }
  }
  await route.fulfill({ json: body })
})
const picker = page.getByRole('button', { name: '召唤智能体', exact: true })
const choose = async name => {
  await picker.click()
  await page.getByRole('option', { name, exact: true }).click()
}
const input = page.locator('.workspace-chat .inline-composer .cm-content')
const expectNewChat = async agentId => {
  await page.waitForURL(`${base}/workspace/chat${agentId ? `?agent=${agentId}` : ''}`)
  await input.waitFor()
  assert.equal(await input.locator('.cm-placeholder').count(), 1, 'Switching opens a fresh composer')
  assert.equal(await page.getByText(/的独立回答|专家正在检查商品。/).count(), 0, 'Switching must not restore history or an active run')
}
const openHistory = async agentId => {
  await page.locator('#workspace-history .session-item').filter({ hasText: `${agentId} 的历史对话` }).last().click()
}
try {
  await page.goto(`${base}/workspace/chat?session=10`)
  const identityLoading = page.getByRole('status', { name: '正在加载智能体信息', exact: true })
  await identityLoading.waitFor()
  const loadingBounds = await page.locator('.workspace-heading .agent-switcher-identity').boundingBox()
  const switchBounds = await picker.boundingBox()
  assert.notEqual(await identityLoading.evaluate(element => getComputedStyle(element).animationName), 'none')
  assert.equal(await page.locator('.workspace-heading .agent-switcher-name').count(), 0, 'No placeholder identity before bootstrap completes')
  releaseBootstrap()
  await page.getByText('1 的独立回答', { exact: true }).waitFor()
  await identityLoading.waitFor({ state: 'detached' })
  assert.deepEqual(await page.locator('.workspace-heading .agent-switcher-identity').boundingBox(), loadingBounds, 'Identity loading must reserve the same space')
  assert.deepEqual(await picker.boundingBox(), switchBounds, 'Switch button must not shift after loading')
  await openResources()
  assert.equal(await resourceLink('基本信息').count(), 0)
  await page.keyboard.press('Escape')
  await input.fill('默认助手草稿')
  await page.waitForFunction(() => sessionStorage.getItem('agent-chat-drafts:1')?.includes('默认助手草稿'))
  await chooseResource('渠道配置')
  await page.getByRole('button', { name: '#10', exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/workspace/assistant/channels')
  assert.ok(requests.some(request => request.includes('/agents/1/channels/weixin')))
  assert.ok(requests.some(request => request.includes('/agents/1/channels/dingtalk')))
  await page.reload()
  await page.getByRole('button', { name: '#10', exact: true }).click()
  await page.waitForURL('**/workspace/chat?session=10')
  await page.getByText('1 的独立回答', { exact: true }).waitFor()
  assert.equal(await input.textContent(), '默认助手草稿')
  await chooseResource('统计信息')
  await page.getByRole('heading', { name: '运行质量', exact: true }).waitFor()
  assert.ok(requests.some(request => request.includes('/agents/1/statistics?days=7')))
  await page.getByRole('tab', { name: '趣点用量', exact: true }).click()
  await page.reload()
  await page.getByRole('heading', { name: '趣点用量', exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/workspace/assistant/statistics')
  assert.equal(await page.locator('.workspace-heading .agent-switcher-name').innerText(), '默认助手')
  assert.equal(await page.locator('.agent-workspace-nav').count(), 0)
  await choose('商品合规专家')
  await expectNewChat(99)
  await openResources()
  assert.equal(await resourceLink('渠道配置').count(), 1)
  await page.keyboard.press('Escape')
  await openHistory(99)
  await page.waitForURL('**/workspace/chat?agent=99&session=990')
  await page.getByText('99 的独立回答', { exact: true }).waitFor()
  assert.equal(await page.locator('.workspace-heading .agent-switcher-name').innerText(), '商品合规专家')
  assert.equal(await page.locator('.workspace-heading .agent-switcher-avatar img').getAttribute('src'), '/characters/cow-v1.svg')
  assert.equal(await input.locator('.cm-placeholder').count(), 1)
  assert.equal(await page.locator('.agent-workspace-nav').count(), 0)
  const center = await page.locator('.chat-center').boundingBox()
  const sidebar = await page.locator('.workspace-sidebar').boundingBox()
  assert.ok(Math.abs(center.x - sidebar.x - sidebar.width) < 2, 'No duplicate expert sidebar')

  // Expert management entries are removed from the workbench More menu.
  await input.fill('专家草稿')
  await openResources()
  assert.deepEqual(await page.getByRole('navigation', { name: '更多', exact: true }).getByRole('link').allTextContents(), ['渠道配置', '统计信息'])
  assert.equal(await resourceLink('基本信息').count(), 0)
  assert.equal(await resourceLink('开放调用').count(), 0)
  assert.equal(await resourceLink('API 调用记录').count(), 0)
  await page.keyboard.press('Escape')
  await chooseResource('统计信息')
  await page.getByRole('heading', { name: '运行质量', exact: true }).waitFor()
  await page.getByRole('tab', { name: 'Token 用量', exact: true }).click()
  assert.equal(await page.locator('.token-metric-grid .metric-item').count(), 4)
  assert.equal(await page.locator('.token-metric-grid').getByText('趣点消耗', { exact: true }).count(), 0)
  await page.reload()
  await page.getByRole('heading', { name: 'Token 用量', exact: true }).waitFor()
  assert.deepEqual(await page.locator('.statistics-tab').allTextContents(), ['运行质量', '趣点用量', 'Token 用量'])
  await page.getByRole('tab', { name: '趣点用量', exact: true }).click()
  const creditValues = page.locator('.credit-metric-grid .metric-item > strong')
  assert.deepEqual(await creditValues.allTextContents(), ['14.00', '3.50', '2.00', '10.00'])
  assert.equal(await page.locator('.bar-credit').count(), 2)
  assert.equal(await page.locator('.credit-source-panel .source-row').count(), 2)
  await mkdir('../output/playwright', { recursive: true })
  await page.screenshot({ path: '../output/playwright/agent-credit-statistics.png', animations: 'disabled' })
  await page.reload()
  await page.getByRole('heading', { name: '趣点用量', exact: true }).waitFor()
  assert.equal(new URL(page.url()).searchParams.get('view'), 'credits')
  await page.locator('.statistics-content .el-segmented').getByText('今天', { exact: true }).click()
  await page.getByText('当前周期暂无趣点消耗', { exact: true }).waitFor()
  assert.deepEqual(await creditValues.allTextContents(), ['0.00', '0.00', '0.00', '0.00'])
  await page.locator('.statistics-content .el-segmented').getByText('近 30 天', { exact: true }).click()
  await page.getByText('按所选 30 个自然日计算', { exact: true }).waitFor()
  assert.deepEqual(await creditValues.allTextContents(), ['14.00', '3.50', '0.47', '10.00'])
  assert.ok(requests.some(request => request.includes('/agents/99/statistics')))
  await openResources()
  assert.equal(await resourceLink('渠道配置').count(), 1)
  await page.keyboard.press('Escape')
  await page.locator('#workspace-history .session-item').filter({ hasText: '99 的历史对话' }).last().click()
  await page.waitForURL('**/workspace/chat?agent=99&session=990')
  await page.getByText('99 的独立回答', { exact: true }).waitFor()
  assert.equal(await input.textContent(), '专家草稿')

  // Resource navigation retains the expert and returns through its own history.
  await chooseResource('连接器')
  await page.locator('.connector-grid').getByText('专家独立 MCP', { exact: true }).waitFor()
  assert.equal(await page.locator('.connector-grid').getByText('系统默认', { exact: true }).count(), 0)
  assert.equal(await page.locator('.connector-grid').getByText('默认助手系统 MCP', { exact: true }).count(), 0)
  const connectionToggle = page.getByRole('switch', { name: '启用 专家独立 MCP', exact: true })
  await connectionToggle.locator('..').click()
  await page.waitForFunction(() => document.querySelector('[role="switch"][aria-label="启用 专家独立 MCP"]')?.getAttribute('aria-checked') === 'false')
  assert.deepEqual(resourceWrites, [{ status: 'disabled', agent_id: 99 }])
  await page.reload()
  await page.locator('.connector-grid').getByText('专家独立 MCP', { exact: true }).waitFor()
  await chooseResource('提示词库')
  await page.locator('.asset-table').getByText('专家独立提示词', { exact: true }).waitFor()
  assert.equal(await page.locator('.asset-table').getByText('默认助手系统提示词', { exact: true }).count(), 0)
  const catalogLoaded = page.waitForRequest(request => {
    const url = new URL(request.url())
    return url.pathname === '/aihub/api/assets/skills/catalog' && url.searchParams.get('agent_id') === '99'
  })
  await chooseResource('技能市场')
  await catalogLoaded
  assert.equal(new URL(page.url()).searchParams.get('agent'), '99')
  await page.locator('#workspace-history .session-item').filter({ hasText: '99 的历史对话' }).last().click()
  await page.waitForURL('**/workspace/chat?agent=99&session=990')
  await page.getByText('99 的独立回答', { exact: true }).waitFor()

  // Refresh keeps the expert, session and resource scope.
  await page.reload()
  await page.getByText('99 的独立回答', { exact: true }).waitFor()
  const filesLoaded = page.waitForResponse(response => response.url().includes('/agents/99/files'))
  await page.getByRole('button', { name: '工作区文件', exact: true }).click()
  await filesLoaded
  await page.getByRole('button', { name: '工作区文件', exact: true }).click()
  await choose('默认助手')
  await expectNewChat(0)
  await chooseResource('连接器')
  await page.locator('.connector-grid').getByText('默认助手系统 MCP', { exact: true }).waitFor()
  assert.equal(await page.locator('.connector-grid').getByText('专家独立 MCP', { exact: true }).count(), 0)
  await chooseResource('提示词模板')
  await page.locator('.asset-table').getByText('默认助手系统提示词', { exact: true }).waitFor()
  assert.equal(await page.locator('.asset-table').getByText('专家独立提示词', { exact: true }).count(), 0)
  await openHistory(1)
  await page.getByText('1 的独立回答', { exact: true }).waitFor()
  await openResources()
  assert.equal(await resourceLink('统计信息').count(), 1)
  await page.keyboard.press('Escape')
  assert.equal(await input.textContent(), '默认助手草稿')

  await choose('商品合规专家')
  await expectNewChat(99)
  await openHistory(99)
  await page.getByText('99 的独立回答', { exact: true }).waitFor()
  await input.fill('检查商品合规')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.getByText('专家正在检查商品。', { exact: true }).waitFor()
  await choose('数据分析专家')
  await page.waitForURL('**/workspace/chat?agent=100')
  await input.waitFor()
  assert.equal(await page.getByText('专家正在检查商品。', { exact: true }).count(), 0)
  assert.equal(await input.locator('.cm-placeholder').count(), 1)
  await choose('商品合规专家')
  await expectNewChat(99)
  await openHistory(99)
  await page.getByText('专家正在检查商品。', { exact: true }).waitFor()
  assert.ok(reconnects > 0, 'Opening history must reconnect to the existing run')
  assert.equal(posts.length, 1, 'Switching must not resubmit the question')
  assert.equal(posts[0].path, '/aihub/api/agents/99/messages')
  assert.equal(posts[0].body.session_id, 990)
  assert.equal(requests.some(request => request.includes('/cancel')), false, 'Switching must not cancel runs')
  assert.ok(requests.some(request => request.includes('/assets/mcp/connections?agent_id=99')), 'MCP lookup must use the expert scope')
  await mkdir('../output/playwright', { recursive: true })
  await picker.click()
  await page.getByRole('option', { name: '数据分析专家', exact: true }).waitFor()
  assert.equal(await page.getByRole('option', { name: '数据分析专家', exact: true }).locator('img').getAttribute('src'), '/characters/sprout-v1.svg')
  await page.getByRole('textbox', { name: '搜索智能体', exact: true }).fill('数据')
  assert.equal(await page.getByRole('option').count(), 1)
  await page.getByRole('textbox', { name: '搜索智能体', exact: true }).fill('')
  await page.getByRole('status', { name: '正在加载智能体', exact: true }).waitFor({ state: 'hidden' })
  await page.screenshot({ path: '../output/playwright/workbench-expert-switch.png', animations: 'disabled' })
  await page.keyboard.press('Escape')

  // New sessions and browser history keep the selected expert.
  await page.getByRole('button', { name: '新建对话', exact: true }).click()
  await page.waitForURL('**/workspace/chat?agent=99')
  await choose('默认助手')
  await page.goBack()
  await page.waitForURL('**/workspace/chat?agent=99')
  await input.waitFor()
  assert.equal(await page.getByText('99 的独立回答', { exact: true }).count(), 0)

  // A failed list refresh keeps the selected expert usable and can be retried.
  failList = true
  await picker.click()
  await page.getByRole('button', { name: '专家列表加载失败，点击重试' }).waitFor()
  failList = false
  await page.getByRole('button', { name: '专家列表加载失败，点击重试' }).click()
  await page.getByRole('button', { name: '专家列表加载失败，点击重试' }).waitFor({ state: 'detached' })
  await page.keyboard.press('Escape')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '打开工作台导航', exact: true }).click()
  await picker.click()
  await page.getByRole('option', { name: '数据分析专家', exact: true }).click()
  await page.waitForURL('**/workspace/chat?agent=100')
  assert.equal(await page.locator('.workspace-sidebar.mobile-open').count(), 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.locator('.agent-switcher-popover:visible').waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '打开工作台导航', exact: true }).click()
  await picker.click()
  await page.getByRole('option', { name: '默认助手', exact: true }).waitFor()
  await page.getByRole('status', { name: '正在加载智能体', exact: true }).waitFor({ state: 'hidden' })
  await page.getByRole('textbox', { name: '搜索智能体', exact: true }).fill('数据')
  await page.locator('.agent-switcher-popover:visible').evaluate(element => Promise.all(
    element.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => {})),
  ))
  await page.screenshot({ path: '../output/playwright/workbench-expert-mobile.png', animations: 'disabled' })
  // Expert detail pages retain their identity, with switching exclusive to the workbench.
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto(`${base}/admin/agents/99/chat?session=990`)
  await page.getByText('专家正在检查商品。', { exact: true }).waitFor()
  assert.equal(await page.locator('.agent-workspace-nav__heading .agent-switcher-name').innerText(), '商品合规专家')
  assert.equal(await picker.count(), 0)
  assert.equal(await page.locator('.agent-workspace-nav__heading .agent-switcher-avatar img').getAttribute('src'), '/characters/cow-v1.svg')
  await openResources()
  assert.deepEqual(await page.getByRole('navigation', { name: '更多', exact: true }).getByRole('link').allTextContents(), ['渠道配置', '统计信息'])
  assert.equal(await page.getByRole('navigation', { name: '更多', exact: true }).getByRole('link', { name: '基本信息', exact: true }).count(), 0)
  assert.equal(await page.getByRole('navigation', { name: '更多', exact: true }).getByRole('link', { name: '开放调用', exact: true }).count(), 0)
  assert.equal(await page.getByRole('navigation', { name: '更多', exact: true }).getByRole('link', { name: 'API 调用记录', exact: true }).count(), 0)
  await page.getByRole('navigation', { name: '更多', exact: true }).getByRole('link', { name: '渠道配置', exact: true }).click()
  await page.getByRole('heading', { name: '渠道配置', exact: true }).waitFor()
  assert.ok(requests.some(request => request.includes('/agents/99/channels/weixin')))
  assert.ok(requests.some(request => request.includes('/agents/99/channels/dingtalk')))
  await page.screenshot({ path: '../output/playwright/workbench-expert-channels.png', animations: 'disabled' })
  await page.goto(`${base}/workspace/chat?agent=99`)
  for (const name of ['基本信息', '统计信息']) {
    await page.locator('.agent-workspace-nav').getByRole('button', { name, exact: true }).click()
    await page.locator('.agent-workspace-nav__item.is-active').filter({ hasText: name }).waitFor()
    assert.equal(await picker.count(), 0, `${name} must not offer assistant switching`)
  }
  await page.screenshot({ path: '../output/playwright/expert-header-identity.png', animations: 'disabled' })
  await page.goto(`${base}/admin/agents/99/channels`)
  await page.waitForURL('**/admin/agents/99')
  await page.goto(`${base}/workspace/agents/99/channels?agent=99`)
  await page.getByRole('heading', { name: '渠道配置', exact: true }).waitFor()
  await page.goto(`${base}/workspace/chat`)
  await picker.waitFor()
  await choose('商品合规专家')
  await expectNewChat(99)
  assert.deepEqual(errors, [])
  console.log('PASS: switching opens new chats, session/resource isolation, refresh, drafts, background run recovery through history, list retry and mobile layout')
} finally {
  await browser.close()
}
