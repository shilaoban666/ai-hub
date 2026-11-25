import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15176'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const openResources = () => page.getByRole('button', { name: '资源与工具', exact: true }).click()
const resourceLink = name => page.getByRole('navigation', { name: '资源与工具', exact: true }).getByRole('link', { name, exact: true })
const chooseResource = async name => {
  await openResources()
  await resourceLink(name).click()
}
page.setDefaultTimeout(12000)
const errors = [], writes = [], requests = []
let userId = 8, published = true
let publicationBlocked = false
const privateResources = ['技能未公开: 商品合规技能', 'MCP 未公开: 合规 MCP', '提示词未公开: 合规提示词']
const model = { id: 1, scope: 'platform', name: '当前用户模型', provider: 'anthropic', api_protocol: 'anthropic-messages' }
const common = { kind: 'expert', runtime_type: 'claude_code', models: [model], default_model_id: 1,
  skills: [], prompt_templates: [], mcp_connections: [] }
const assistant = { ...common, id: 1, user_id: 8, kind: 'personal_default', name: '默认助手', icon: 'H' }
const mine = { ...common, id: 100, user_id: 8, name: '我的分析专家', icon: '@sprout', can_edit: true }
const shared = { ...common, id: 99, user_id: 7, name: '公开合规专家', icon: '@cow', is_public: true,
  description: '由发布者维护的合规专家', system_prompt: '你是合规专家，使用绑定的公开资源回答。',
  skills: [{ id: 9, name: '商品合规技能' }], skill_ids: [9], prompt_template_ids: [91],
  prompt_templates: [{ id: 91, name: '合规提示词', category: '商品合规', content: '按发布者配置的规则检查商品。' }],
  mcp_connections: [{ id: 92, name: '合规 MCP', auth_mode: 'current_user' }] }
const release = { id: 901, version: '1.0.0', installable: true }
const catalogSkill = { skill_id: 9, name: '商品合规技能', author: '发布者', description: '商品审核规则与操作说明',
  is_public: true, releases: [release], latest_release: release, user_installation: { id: 90, release_id: 901 },
  effective_release_id: 901, installed_user_count: 12, download_count: 34 }
const connection = { id: 92, name: '合规 MCP', description: '合规检索', transport_type: 'http',
  auth_mode: 'current_user', status: 'active', origins: ['public'] }
const visitorStructure = {}
await page.addInitScript(() => localStorage.setItem('access_token', 'public-agent-test'))
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), path = url.pathname
  if (!/^\/(aihub|iam)\/api\//.test(path)) return route.continue()
  requests.push(`${req.method()} ${path}${url.search}`)
  if (req.method() !== 'GET') writes.push({ method: req.method(), path, body: req.postDataJSON() })
  let body = { items: [], total: 0 }
  if (path === '/iam/api/me') body = { id: userId, username: '测试用户', permissions: [] }
  else if (path === '/iam/api/users/') body = { items: [{ id: 7, first_name: '合规专家作者', username: 'publisher' }] }
  else if (path.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
  else if (path.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100, display_name: '趣点' }
  else if (path === '/aihub/api/public/agents') body = { items: published ? [shared] : [], total: published ? 1 : 0 }
  else if (path === '/aihub/api/agents') body = { items: userId === 7 ? [{ ...shared, can_edit: true }] : [mine], total: 1 }
  else if (/\/agents\/99\/(publish|unpublish)$/.test(path)) {
    assert.equal(userId, 7, 'Only the publisher can change visibility')
    if (publicationBlocked && path.endsWith('/publish')) return route.fulfill({ status: 409, json: {
      code: 409, message: '智能体包含私有资源，全部公开后才能发布', data: { items: privateResources },
    } })
    published = path.endsWith('/publish')
    shared.is_public = published
    body = { ...shared, can_edit: true }
  }
  else if (/\/agents\/\d+$/.test(path)) {
    const id = Number(path.split('/').at(-1))
    if (id === 99 && !published && userId !== 7) return route.fulfill({ status: 403, json: { detail: '智能体未公开或已不可用' } })
    body = id === 99 ? { ...shared, can_edit: userId === 7 } : id === 100 ? mine : assistant
  } else if (/\/models$/.test(path)) body = { items: [model, { ...model, id: 2, name: '自定义测试模型', scope: 'user' }] }
  else if (path === '/aihub/api/assets/skills/catalog') {
    body = url.searchParams.get('agent_id') === '99' ? { items: [catalogSkill], total: 1 } : { items: [], total: 0 }
  }
  else if (path === '/aihub/api/assets/mcp/connections') {
    body = url.searchParams.get('agent_id') === '99' ? { items: [connection], total: 1 } : { items: [], total: 0 }
  }
  else if (path === '/aihub/api/assets/skills/releases/901/files') body = {
    files: [{ type: 'file', label: 'SKILL.md', path: 'SKILL.md', content: '# 商品合规技能\n检查商品风险的完整规则。' }],
  }
  else if (path.endsWith('/runtime-status')) body = { status: 'not_applicable', runtime_type: 'claude_code' }
  else if (path.endsWith('/skills/sync')) body = { status: 'synced' }
  else if (path.endsWith('/files')) body = { type: 'dir', items: [] }
  else if (path === '/aihub/api/agents/99/messages') {
    return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ type: 'text', content: '公开专家的回答' })}\n\ndata: ${JSON.stringify({ type: 'done' })}\n\n` })
  }
  await route.fulfill({ json: body })
})
const picker = page.getByRole('button', { name: '召唤智能体', exact: true })
const config = page.locator('.config-form')
try {
  await page.goto(`${base}/workspace/chat`)
  await picker.click()
  const defaultOption = page.getByRole('option', { name: '默认助手', exact: true })
  const mineOption = page.getByRole('option', { name: '我的分析专家', exact: true })
  const sharedOption = page.getByRole('option', { name: '公开合规专家', exact: true })
  await sharedOption.waitFor()
  assert.equal(await defaultOption.locator('.origin-badge').textContent(), '默认')
  assert.equal(await mineOption.locator('.origin-badge').textContent(), '我的')
  assert.equal(await sharedOption.locator('.origin-badge').textContent(), '公开')
  assert.equal(await sharedOption.locator('.agent-switcher-option-name').evaluate(el => getComputedStyle(el).fontWeight), '400')
  await sharedOption.locator('.agent-card-author').getByText('作者：合规专家作者', { exact: true }).waitFor()
  assert.equal(await sharedOption.locator('.agent-card-description').textContent(), shared.description)
  assert.equal(await sharedOption.locator('.expertise-tag').textContent(), '商品合规技能')
  assert.equal(await defaultOption.locator('.expertise-empty').textContent(), '无')
  const search = page.getByRole('textbox', { name: '搜索智能体', exact: true })
  for (const query of ['合规专家作者', '由发布者维护', '商品合规技能']) {
    await search.fill(query)
    await sharedOption.waitFor()
    assert.equal(await page.getByRole('option').count(), 1)
  }
  await search.fill('不存在的智能体')
  await page.getByText('无匹配智能体', { exact: true }).waitFor()
  await search.fill('')
  await mkdir('../output/playwright', { recursive: true })
  await page.screenshot({ path: '../output/playwright/public-agent-switcher.png' })
  await sharedOption.click()
  await page.waitForURL('**/workspace/chat?agent=99')
  const input = page.getByPlaceholder('输入问题或任务')
  await input.waitFor()
  assert.equal(await input.locator('.cm-placeholder').count(), 1)
  await picker.click()
  assert.equal(await sharedOption.locator('.agent-switcher-option-name').evaluate(el => getComputedStyle(el).fontWeight), '600')
  await page.keyboard.press('Escape')
  const checkPublicSection = async label => {
    if (label === '基本信息') {
      const description = page.getByPlaceholder('一句话描述这个智能体的用途')
      await description.waitFor()
      assert.equal(await description.inputValue(), shared.description)
      for (const field of await config.locator('input:visible, textarea:visible').all()) {
        assert.equal(await field.evaluate(el => el.readOnly || el.disabled || !!el.closest('.is-disabled')), true, await field.evaluate(el => el.outerHTML))
      }
      assert.equal(await page.getByRole('button', { name: '保存', exact: true }).isDisabled(), true)
      assert.equal(await page.getByRole('button', { name: '更换头像', exact: true }).isDisabled(), true)
      visitorStructure.basic = await config.locator('.el-form-item__label').allTextContents()
    } else {
      const root = page.locator('.resource-center')
      const expected = { '技能市场': '商品合规技能', '提示词模板': '合规提示词', '连接器': '合规 MCP' }[label]
      await root.getByText(expected, { exact: true }).waitFor()
      for (const button of await root.getByRole('button', { name: /^(从资源中心添加|连接|取消连接|安装|升级|卸载|删除|移除|启用|停用|认证配置)$/ }).all()) {
        assert.equal(await button.isDisabled(), true, `${label} mutations must be disabled`)
      }
      assert.equal(await root.locator('.resource-create-button').count(), 0)
      if (label === '技能市场') {
        assert.equal(await root.getByText('发布者 · v1.0.0', { exact: true }).count(), 1)
        await root.getByRole('button', { name: '已安装', exact: true }).click()
        await root.locator('.skill-card').waitFor()
        await root.locator('.skill-card h3').click()
        await page.locator('.skill-detail .file-content').getByText('检查商品风险的完整规则。', { exact: true }).waitFor()
        await page.locator('.skill-detail').getByRole('button', { name: '关闭', exact: true }).click()
      } else {
        visitorStructure[label] = await root.locator(label === '连接器' ? '.connector-card h3' : 'thead th .cell').allTextContents()
        const search = root.getByPlaceholder(label === '提示词模板' ? '搜索模板' : '搜索连接器')
        await search.fill('不存在的内容')
        await root.getByText(label === '提示词模板' ? '没有匹配的提示词模板' : '没有匹配的连接器', { exact: true }).waitFor()
        await search.fill('')
        await root.getByText(expected, { exact: true }).waitFor()
      }
    }
  }
  for (const label of ['基本信息', '技能市场', '提示词模板', '连接器']) {
    await chooseResource(label)
    await checkPublicSection(label)
    await page.reload()
    await checkPublicSection(label)
    await page.screenshot({ path: `../output/playwright/public-agent-${label}.png`, animations: 'disabled' })
  }
  assert.equal(requests.some(value => value.includes('/assets/mcp/connections?agent_id=99')), true)
  assert.equal(requests.some(value => /mcp.*headers/.test(value)), false, 'Private credentials must not be requested')
  await page.getByRole('button', { name: '新建对话', exact: true }).click()
  await input.fill('请检查商品合规')
  await input.press('Enter')
  await page.getByText('公开专家的回答', { exact: true }).waitFor()
  assert.equal(writes.filter(req => req.path.endsWith('/messages')).length, 1)
  assert.equal(writes.find(req => req.path.endsWith('/messages')).path, '/aihub/api/agents/99/messages')
  assert.equal(writes.some(req => req.method === 'PUT' || req.method === 'DELETE' || req.path.includes('/bindings')), false)

  // Direct links must be just as read-only as the workbench entry.
  await page.goto(`${base}/admin/agents/99`)
  await checkPublicSection('基本信息')
  assert.equal(await page.getByRole('button', { name: /^(设为公开|设为私有)$/ }).count(), 0)
  assert.equal(await picker.count(), 0)
  published = false
  await page.goto(`${base}/workspace/skills?agent=99`)
  await page.getByText('智能体未公开或已不可用', { exact: true }).first().waitFor()
  assert.equal(await config.count(), 0)
  assert.equal(await page.locator('.resource-center').count(), 0)

  // A publisher sees one option with both labels and retains configuration editing.
  published = true
  userId = 7
  await page.goto(`${base}/workspace/chat`)
  await picker.click()
  await sharedOption.waitFor()
  assert.equal(await sharedOption.count(), 1)
  assert.deepEqual(await sharedOption.locator('.origin-badge').allTextContents(), ['我的', '公开'])
  await sharedOption.click()
  await chooseResource('基本信息')
  await page.getByPlaceholder('一句话描述这个智能体的用途').waitFor()
  assert.equal(await page.getByRole('button', { name: '保存', exact: true }).count(), 1)
  assert.equal(await page.getByRole('button', { name: '保存', exact: true }).isEnabled(), true)
  assert.deepEqual(await config.locator('.el-form-item__label').allTextContents(), visitorStructure.basic)
  for (const label of ['技能市场', '提示词模板', '连接器']) {
    await chooseResource(label)
    const root = page.locator('.resource-center')
    await root.getByText({ '技能市场': '商品合规技能', '提示词模板': '合规提示词', '连接器': '合规 MCP' }[label], { exact: true }).waitFor()
    const button = root.getByRole('button', { name: label === '技能市场' ? '卸载' : label === '连接器' ? '取消连接' : '从资源中心添加', exact: true })
    await button.waitFor()
    assert.equal(await button.isEnabled(), true)
    if (label !== '技能市场') assert.deepEqual(await root.locator(label === '连接器' ? '.connector-card h3' : 'thead th .cell').allTextContents(), visitorStructure[label])
  }
  await chooseResource('基本信息')
  const actions = page.locator('.agent-workspace-header .workspace-actions')
  const modelSelect = config.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: '默认模型' }) }).locator('.el-select')
  await modelSelect.click()
  const customModelOption = page.getByRole('option').filter({ hasText: '自定义测试模型' })
  await customModelOption.waitFor()
  assert.equal(await customModelOption.getAttribute('aria-disabled'), 'true')
  await page.keyboard.press('Escape')
  await actions.getByRole('button', { name: '设为私有', exact: true }).click()
  await actions.getByRole('button', { name: '设为公开', exact: true }).waitFor()
  assert.equal(published, false)
  await modelSelect.click()
  await customModelOption.waitFor()
  assert.notEqual(await customModelOption.getAttribute('aria-disabled'), 'true')
  await page.keyboard.press('Escape')
  publicationBlocked = true
  await actions.getByRole('button', { name: '设为公开', exact: true }).click()
  const publicationError = page.getByRole('dialog', { name: '无法设为公开' })
  await publicationError.waitFor()
  assert.deepEqual(await publicationError.locator('li').allTextContents(), privateResources)
  assert.equal(await publicationError.count(), 1)
  assert.equal(await page.locator('.el-message--error').count(), 0)
  assert.equal(published, false)
  await page.screenshot({ path: '../output/playwright/agent-publication-resources.png', animations: 'disabled' })
  await publicationError.getByRole('button', { name: '知道了' }).click()
  await publicationError.waitFor({ state: 'hidden' })
  publicationBlocked = false
  await actions.getByRole('button', { name: '设为公开', exact: true }).click()
  await actions.getByRole('button', { name: '设为私有', exact: true }).waitFor()
  assert.equal(published, true)
  await page.goto(`${base}/admin/agents/99`)
  await actions.getByRole('button', { name: '设为私有', exact: true }).waitFor()
  await page.screenshot({ path: '../output/playwright/agent-publish-header.png', animations: 'disabled' })
  assert.deepEqual(errors, [])
  console.log('PASS: three badges, public direct chat, read-only resources/basic information, reload/direct links, revocation, owner deduplication/editing')
} finally {
  await browser.close()
}
