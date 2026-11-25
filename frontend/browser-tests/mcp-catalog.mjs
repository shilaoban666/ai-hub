import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const output = path.resolve('node_modules/.cache/mcp-catalog')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
page.setDefaultTimeout(15000)
await page.addInitScript(() => localStorage.setItem('access_token', 'mcp-catalog-browser-test'))
const errors = []
const mutations = []
const reads = []
let visitor = false
let unavailable = false
let sequence = 100
const resource = (id, name, extra = {}) => ({ id, name, type: 'streamable_http', author: '吴张洁', description: `${name} 提供业务查询和知识检索。`, usage_instructions: '### 使用方式\n连接后即可在对话中使用。', ...extra })
const mine = [resource(1, 'online-mcp', { is_public: true }), resource(2, 'seller-sprite', { is_public: false })]
const fullDescription = Array.from({ length: 8 }, (_, index) => `知识检索说明 ${index + 1}：连接后可查询团队文档和业务知识。`).join('\n')
const publicRows = [mine[0], resource(3, 'online-knowledge-base', { description: fullDescription }), resource(4, 'mcp-server', { author: '  ' })]
const systemDefinitions = [{ id: 11, source_mcp_service_id: 1, name: 'online-mcp', description: 'Online MCP 服务，提供供应商、商品等模块查询。', author: '吴张洁', transport_type: 'streamable_http', scope: 'system', status: 'published', auth_mode: 'current_user', origins: ['mine', 'public'] }]
const personal = new Map([[0, [{ id: 51, definition_id: 31, source_mcp_service_id: 2, name: 'seller-sprite', author: '吴张洁', description: '卖家精灵', transport_type: 'streamable_http', status: 'disabled', auth_mode: 'manual', origins: ['mine'] }]], [99, []]])
const pendingDefinitions = new Map()
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const url = new URL(route.request().url())
  const pathname = url.pathname
  if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
  const method = route.request().method()
  const data = ['POST', 'PUT'].includes(method) ? route.request().postDataJSON() : null
  if (method === 'GET') reads.push(pathname + url.search)
  else mutations.push({ pathname, method, data })
  let body = { total: 0, items: [] }
  if (pathname === '/iam/api/me') body = { id: 7, username: 'tester', first_name: '吴张洁', is_superuser: true, permissions: [] }
  else if (pathname.endsWith('/agents/99')) body = { id: 99, name: '业务智能体', user_id: visitor ? 8 : 7, can_edit: !visitor, is_public: visitor, skill_ids: [], prompt_template_ids: [] }
  else if (pathname === '/aihub/api/mcps') {
    if (unavailable) return route.fulfill({ status: 400, json: { detail: '目录加载失败' } })
    body = { total: mine.length, items: mine }
  }
  else if (pathname === '/aihub/api/public/mcps') body = { total: publicRows.length, items: publicRows }
  else if (/\/(?:public\/)?mcps\/\d+$/.test(pathname)) {
    const id = Number(pathname.split('/').at(-1))
    body = { ...[...mine, ...publicRows].find(row => row.id === id), config: [3, 5].includes(id) ? JSON.stringify({ url: 'https://example.com/mcp', headers: { Authorization: id === 5 ? 'Bearer own-saved-secret' : '隐藏' } }) : '{}' }
  }
  else if (pathname.endsWith('/assets/admin/mcp/definitions')) {
    if (method === 'POST') {
      const source = publicRows.find(row => row.id === data.source_mcp_service_id)
      body = { ...source, id: ++sequence, source_mcp_service_id: source.id, transport_type: source.type, status: 'published', scope: 'system', origins: ['public'] }
      systemDefinitions.push(body)
    } else body = { total: systemDefinitions.length, items: systemDefinitions }
  }
  else if (pathname.endsWith('/assets/mcp/definitions/import')) {
    const source = [...mine, ...publicRows].find(row => row.id === data.source_mcp_service_id)
    body = { id: ++sequence, name: source.name, latest_revision: { id: sequence * 10 } }
    pendingDefinitions.set(body.id, source)
  }
  else if (pathname.endsWith('/assets/mcp/connections')) {
    const scope = Number(data?.agent_id || url.searchParams.get('agent_id') || 0)
    if (method === 'POST') {
      const source = pendingDefinitions.get(data.definition_id)
      body = { id: ++sequence, definition_id: data.definition_id, source_mcp_service_id: source.id, name: source.name, author: source.author, transport_type: source.type, status: 'active', auth_mode: 'manual', origins: ['public'] }
      personal.get(scope).push(body)
    } else {
      const system = scope ? [] : systemDefinitions.map(row => ({ ...row, id: `system-${row.id}`, definition_id: row.id, status: 'active', is_system: true }))
      const rows = [...system, ...personal.get(scope)]
      body = { items: rows, total: rows.length }
    }
  }
  else if (pathname.endsWith('/headers')) {
    body = { auth_mode: 'manual', inherit_system: true, system_auth_mode: 'current_user', headers: [] }
  }
  else if (pathname.endsWith('/inspect')) body = { tools: [{ name: 'search', description: '搜索知识' }], resources: [], prompts: [] }
  else if (pathname.endsWith('/status')) {
    const id = Number(pathname.split('/').at(-2))
    const connection = [...personal.values()].flat().find(row => row.id === id)
    connection.status = data.status
    body = connection
  }
  else if (method === 'DELETE' && /\/assets\/mcp\/connections\//.test(pathname)) {
    const id = Number(pathname.split('/')[6])
    const scope = pathname.includes('/bindings/') ? Number(pathname.split('/').at(-1)) : 0
    personal.set(scope, personal.get(scope).filter(row => row.id !== id))
    body = { status: 'deleted' }
  }
  else if (method === 'DELETE' && /\/assets\/mcp\/definitions\/\d+$/.test(pathname)) {
    const id = Number(pathname.split('/').at(-1))
    const index = systemDefinitions.findIndex(row => row.id === id)
    if (index !== -1) systemDefinitions.splice(index, 1)
    body = { status: 'deleted' }
  }
  await route.fulfill({ json: body })
})

const base = process.env.CONNECTOR_TEST_URL || 'http://127.0.0.1:15173'
const library = page.locator('.connector-library')
const card = name => library.locator('.connector-card').filter({ has: page.getByRole('heading', { name, exact: true }) })
const range = () => library.getByRole('group', { name: '连接器范围', exact: true })
const sourceTabs = () => library.getByRole('group', { name: '连接器来源', exact: true })
const ready = () => page.locator('.connector-grid > .el-loading-mask').waitFor({ state: 'hidden' })
const confirm = () => page.locator('.el-message-box').getByRole('button', { name: '确定', exact: true }).click()
try {
  await page.goto(`${base}/admin/workspace/connectors`)
  await card('online-mcp').waitFor()
  await ready()
  assert.equal(await library.locator('.connector-card').count(), 4)
  assert.equal(await card('online-mcp').count(), 1, 'System connection and source must be one card')
  assert.equal(await card('online-mcp').getByText('吴张洁', { exact: true }).count(), 1)
  assert.equal(await card('online-mcp').getByRole('button', { name: '取消连接', exact: true }).count(), 0)
  assert.equal(await card('mcp-server').locator('.connector-author').getByText('无', { exact: true }).count(), 1)
  assert.equal(await library.getByRole('button', { name: /安装|卸载|升级/ }).count(), 0)
  assert.equal(await library.getByRole('button', { name: '从资源中心添加', exact: true }).count(), 0)
  const descriptionSizes = await library.locator('.connector-description').evaluateAll(elements => elements.map(element => ({
    height: element.getBoundingClientRect().height, lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
  })))
  assert(descriptionSizes.every(({ height, lineHeight }) => Math.abs(height - 2 * lineHeight) < 1), 'Every description occupies exactly two lines, including long text')
  assert(await card('online-knowledge-base').locator('.connector-description').evaluate(element => element.scrollHeight > element.clientHeight), 'Long descriptions are clipped within two lines')
  const rowSizes = await library.locator('.connector-card').evaluateAll(elements => elements.slice(0, 3).map(element => element.getBoundingClientRect().height))
  assert(rowSizes.every(height => Math.abs(height - rowSizes[0]) < 1), 'Cards in the same row remain equal in height')
  const plainCard = await card('mcp-server').boundingBox()
  assert(plainCard.height < rowSizes[0], 'A row without authentication does not reserve authentication space')
  const plainGap = await card('mcp-server').evaluate(element => element.querySelector('.connector-card__actions').getBoundingClientRect().top - element.querySelector('.connector-description').getBoundingClientRect().bottom)
  assert(plainGap <= 16, 'Cards without authentication have no extra action padding')
  await page.screenshot({ path: path.join(output, 'desktop.png'), animations: 'disabled' })

  await range().getByRole('button', { name: '已连接', exact: true }).click()
  assert.equal(await library.locator('.connector-card').count(), 2, 'Disabled connectors are still connected')
  await sourceTabs().getByRole('button', { name: '系统默认', exact: true }).click()
  assert.equal(await library.locator('.connector-card').count(), 1)
  await sourceTabs().getByRole('button', { name: '全部', exact: true }).click()
  await range().getByRole('button', { name: '全部', exact: true }).click()
  await library.getByPlaceholder('搜索连接器').fill('吴张洁')
  assert.equal(await library.locator('.connector-card').count(), 3, 'Search includes authors')
  await library.getByPlaceholder('搜索连接器').fill('不存在')
  await library.getByText('没有匹配的连接器', { exact: true }).waitFor()
  await library.getByPlaceholder('搜索连接器').fill('')

  await card('online-knowledge-base').getByRole('heading').click()
  const details = page.getByRole('dialog', { name: '连接器详情', exact: true })
  await details.getByRole('heading', { name: 'online-knowledge-base', exact: true }).waitFor()
  assert.equal(await details.locator('.detail-description').textContent(), fullDescription)
  assert(await details.locator('.detail-description').evaluate(element => element.clientHeight > 105), 'Dialog expands the full description beyond the card line limit')
  assert.equal(await details.getByText('未连接', { exact: true }).count(), 0)
  assert.equal(await details.getByRole('button', { name: '关闭', exact: true }).count(), 0)
  await page.screenshot({ path: path.join(output, 'detail-desktop.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'detail-mobile.png'), animations: 'disabled' })
  assert(await details.evaluate(element => element.scrollWidth <= element.clientWidth), 'Mobile dialog content must not overflow horizontally')
  await page.setViewportSize({ width: 1440, height: 1100 })
  await details.getByRole('button', { name: '连接', exact: true }).click()
  const auth = page.locator('.mcp-import-header-dialog')
  assert.equal(await auth.getByRole('radio', { name: '手动配置', exact: true }).isChecked(), true)
  assert.equal(await auth.getByRole('textbox', { name: '请求头名称 1', exact: true }).inputValue(), 'Authorization')
  assert.equal(await auth.getByRole('textbox', { name: '请求头值 1', exact: true }).inputValue(), '')
  await auth.getByRole('button', { name: '保存并继续', exact: true }).click()
  assert.equal(mutations.filter(row => row.pathname.includes('/assets/mcp/')).length, 0, 'Public header values must be supplied before connecting')
  await auth.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(mutations.filter(row => row.pathname.includes('/assets/mcp/')).length, 0, 'Cancelling authentication must not create a connection')
  await details.getByRole('button', { name: '连接', exact: true }).click()
  await auth.getByRole('textbox', { name: '请求头值 1', exact: true }).fill('Bearer destination-only')
  await page.screenshot({ path: path.join(output, 'connect-auth-public.png'), animations: 'disabled' })
  await auth.getByRole('button', { name: '保存并继续', exact: true }).click()
  await card('online-knowledge-base').getByRole('button', { name: '取消连接', exact: true }).waitFor()
  assert.deepEqual(mutations.find(row => row.pathname.endsWith('/assets/mcp/definitions/import')).data.secrets, { headers: { Authorization: 'Bearer destination-only' } })
  assert.equal(mutations.find(row => row.pathname.endsWith('/assets/mcp/connections')).data.auth_mode, 'manual')
  assert.equal(await card('online-knowledge-base').count(), 1)
  await details.getByRole('button', { name: '取消连接', exact: true }).waitFor()
  await details.locator('.el-dialog__headerbtn').click()

  await card('seller-sprite').getByRole('heading').click()
  assert.equal(await details.locator('.connector-source-badge').textContent(), '我的')
  await details.locator('.connection-toggle .el-switch').click()
  await card('seller-sprite').getByRole('switch', { name: '启用 seller-sprite', checked: true, exact: true }).waitFor({ state: 'attached' })
  await details.getByRole('switch', { name: '启用 seller-sprite', checked: true, exact: true }).waitFor({ state: 'attached' })
  await page.screenshot({ path: path.join(output, 'detail-connected.png'), animations: 'disabled' })
  await details.getByRole('button', { name: '认证配置', exact: true }).click()
  const config = page.locator('.mcp-auth-dialog:not(.mcp-import-header-dialog)')
  await config.getByText('不发送认证', { exact: true }).click()
  await config.getByRole('button', { name: '保存配置', exact: true }).click()
  await config.waitFor({ state: 'hidden' })
  assert.equal(mutations.at(-1).data.auth_mode, 'none')
  await details.getByRole('button', { name: '查看资源', exact: true }).click()
  const inspector = page.locator('.mcp-inspection-dialog')
  await inspector.getByText('search', { exact: true }).waitFor()
  await inspector.locator('.el-dialog__headerbtn').click()
  await details.locator('.el-dialog__headerbtn').click()

  await range().getByRole('button', { name: '已连接', exact: true }).click()
  await card('online-knowledge-base').getByRole('heading').click()
  await details.getByRole('button', { name: '取消连接', exact: true }).click()
  const before = mutations.length
  await page.locator('.el-message-box').getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(mutations.length, before)
  await details.getByRole('button', { name: '取消连接', exact: true }).click()
  await confirm()
  await card('online-knowledge-base').waitFor({ state: 'hidden' })
  await details.getByRole('button', { name: '连接', exact: true }).waitFor()
  await details.locator('.el-dialog__headerbtn').click()
  await range().getByRole('button', { name: '全部', exact: true }).click()
  await card('online-knowledge-base').getByRole('button', { name: '连接', exact: true }).waitFor()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'mobile.png'), animations: 'disabled' })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile page must not overflow horizontally')
  await page.setViewportSize({ width: 1440, height: 1100 })

  await page.goto(`${base}/admin/workspace/connectors?agent=99`)
  await card('online-mcp').getByRole('button', { name: '连接', exact: true }).waitFor()
  await card('mcp-server').getByRole('button', { name: '连接', exact: true }).click()
  await card('mcp-server').getByRole('button', { name: '取消连接', exact: true }).waitFor()
  assert.equal(mutations.findLast(row => row.pathname.endsWith('/assets/mcp/connections')).data.agent_id, 99)
  await card('mcp-server').getByRole('button', { name: '取消连接', exact: true }).click()
  await confirm()
  await card('mcp-server').getByRole('button', { name: '连接', exact: true }).waitFor()
  assert(mutations.at(-1).pathname.endsWith('/bindings/99'), 'Only the current agent binding is removed')
  assert.equal(personal.get(0).length, 1, 'Agent mutations preserve workbench connections')

  personal.get(99).push({ ...personal.get(0)[0], id: 71 })
  visitor = true
  const readOffset = reads.length
  await page.reload()
  await card('seller-sprite').waitFor()
  await ready()
  assert.equal(await library.locator('.connector-card').count(), 1)
  assert.equal(await card('seller-sprite').getByRole('button', { name: '取消连接', exact: true }).isDisabled(), true)
  assert.equal(await card('seller-sprite').getByRole('button', { name: '认证配置', exact: true }).isDisabled(), true)
  await card('seller-sprite').getByRole('heading').click()
  assert.equal(await details.getByRole('button', { name: '认证配置', exact: true }).isDisabled(), true)
  assert.equal(await details.getByRole('button', { name: '取消连接', exact: true }).isDisabled(), true)
  assert.equal(await details.getByRole('switch', { name: '启用 seller-sprite', exact: true }).isDisabled(), true)
  await details.locator('.el-dialog__headerbtn').click()
  assert.equal(await library.locator('.resource-create-button').count(), 0)
  assert.equal(reads.slice(readOffset).some(url => /^\/aihub\/api\/(public\/)?mcps\?/.test(url)), false)
  visitor = false

  await page.goto(`${base}/admin/workbench-settings?tab=resources`)
  await page.getByRole('button', { name: 'MCP', exact: true }).click()
  await card('online-mcp').getByRole('button', { name: '取消连接', exact: true }).waitFor()
  assert.equal(await card('seller-sprite').count(), 0, 'System defaults only list public catalog sources')
  await card('mcp-server').getByRole('button', { name: '连接', exact: true }).click()
  await card('mcp-server').getByRole('button', { name: '取消连接', exact: true }).waitFor()
  assert.equal(mutations.at(-1).data.source_mcp_service_id, 4)
  await card('mcp-server').getByRole('button', { name: '取消连接', exact: true }).click()
  await confirm()
  await card('mcp-server').getByRole('button', { name: '连接', exact: true }).waitFor()

  await card('online-knowledge-base').getByRole('button', { name: '连接', exact: true }).click()
  await auth.getByText('手动配置', { exact: true }).waitFor()
  await auth.getByText('当前登录身份', { exact: true }).click()
  assert.equal(await auth.getByRole('textbox', { name: '请求头名称 1', exact: true }).count(), 0)
  await auth.getByRole('button', { name: '保存并继续', exact: true }).click()
  await card('online-knowledge-base').getByRole('button', { name: '取消连接', exact: true }).waitFor()
  assert.equal(mutations.findLast(row => row.pathname.endsWith('/assets/admin/mcp/definitions')).data.auth_mode, 'current_user')
  assert.deepEqual(mutations.findLast(row => row.pathname.endsWith('/assets/admin/mcp/definitions')).data.headers, {})

  mine.push(resource(5, 'own-header-mcp'))
  await page.goto(`${base}/admin/workspace/connectors`)
  await card('own-header-mcp').getByRole('button', { name: '连接', exact: true }).click()
  assert.equal(await auth.getByRole('radio', { name: '手动配置', exact: true }).isChecked(), true)
  await auth.getByPlaceholder('已配置，留空保留；输入新值可替换').waitFor()
  await page.screenshot({ path: path.join(output, 'connect-auth-owned.png'), animations: 'disabled' })
  await auth.getByText('不发送认证', { exact: true }).click()
  assert.equal(await auth.getByRole('textbox', { name: '请求头名称 1', exact: true }).count(), 0)
  await auth.getByText('手动配置', { exact: true }).click()
  assert.equal(await auth.getByRole('textbox', { name: '请求头名称 1', exact: true }).inputValue(), 'Authorization')
  await auth.getByRole('button', { name: '保存并继续', exact: true }).click()
  await card('own-header-mcp').getByRole('button', { name: '取消连接', exact: true }).waitFor()
  assert.deepEqual(mutations.findLast(row => row.pathname.endsWith('/assets/mcp/definitions/import')).data.secrets, { headers: { Authorization: 'Bearer own-saved-secret' } })

  unavailable = true
  await page.goto(`${base}/admin/workspace/connectors`)
  await library.getByRole('alert').getByText('目录加载失败', { exact: true }).waitFor()
  assert.equal(await library.locator('.connector-card').count(), 0, 'Failed status/catalog loads must not show unsafe connect actions')
  unavailable = false
  await library.getByRole('button', { name: '重试', exact: true }).click()
  await card('online-mcp').waitFor()
  assert.deepEqual(errors, [])
  console.log('Connector catalog browser checks passed: cards, filters, authors, authentication, connect/cancel, scope isolation, shared read-only, system defaults, retry, desktop and mobile.')
} finally {
  await browser.close()
}
