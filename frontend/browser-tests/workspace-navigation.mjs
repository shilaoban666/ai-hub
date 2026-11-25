import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const model = { id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'platform' }
const assistant = { id: 1, name: '默认助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', models: [model], default_model_id: 1 }
const credit = { claimed_today: true, available_balance: 0, display_name: '积分' }
const session = { id: 10, title: '整理项目进度', source: 'web', message_count: 2, created_at: new Date().toISOString() }
const otherSession = { ...session, id: 11, title: '梳理本周待办' }
const history = [session, otherSession, ...[
  '分析本周销售数据', '整理产品需求文档', '帮我优化这段文案', '客户反馈分类汇总',
  '梳理接口调用流程', '生成周会纪要',
].map((title, index) => ({ ...session, id: 20 + index, title,
  created_at: new Date(Date.now() - (index + 1) * 86400000).toISOString() }))]
const errors = []

async function setupPage(viewport) {
  const page = await browser.newPage({ viewport })
  page.setDefaultTimeout(10000)
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    if (location.pathname !== '/oauth/callback') return
    sessionStorage.setItem('oauth_state', 'test-state')
    sessionStorage.setItem('oauth_code_verifier', 'test-verifier')
  })
  await page.route('**/*', async route => {
    const { pathname } = new URL(route.request().url())
    if (pathname.endsWith('/o/token/')) {
      return route.fulfill({ headers: { 'access-control-allow-origin': '*' }, json: { access_token: 'test-token', refresh_token: 'test-refresh' } })
    }
    if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
    let body = { items: [], total: 0 }
    if (pathname === '/iam/api/me') body = { id: 7, username: '林小满', email: 'xiaoman@example.test', permissions: [] }
    else if (pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant, credit }
    else if (pathname.endsWith('/credits/me')) body = credit
    else if (/\/agents\/1$/.test(pathname)) body = assistant
    else if (pathname.endsWith('/sessions')) body = { items: history, total: history.length }
    else if (pathname.endsWith('/sessions/10/messages')) body = { session, items: [{ id: 1, role: 'user', content: '查看项目进度' }] }
    else if (pathname.endsWith('/models')) body = { items: [model], total: 1 }
    else if (pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
    else if (pathname.endsWith('/files')) body = { files: [] }
    await route.fulfill({ json: body })
  })
  return page
}

const callback = base + '/oauth/callback?code=test-code&state=test-state'
const adminSidebar = page => page.locator('.product-sidebar')
const workSidebar = page => page.getByRole('complementary', { name: '工作台侧栏' })

try {
  const page = await setupPage({ width: 1440, height: 900 })
  await page.goto(callback)
  await page.waitForURL('**/workspace/chat')
  await workSidebar(page).getByText(session.title, { exact: true }).waitFor()
  assert.equal(await adminSidebar(page).count(), 0)
  assert.equal(await workSidebar(page).getByRole('button', { name: '搜索对话', exact: true }).count(), 0)
  const historyRow = workSidebar(page).locator('.session-item').filter({ hasText: session.title })
  assert.match(await historyRow.locator('.session-time').innerText(), /^\d{2}:\d{2}$/)
  await historyRow.getByRole('button', { name: session.title, exact: true }).press('Enter')
  await page.waitForURL('**/workspace/chat?session=10')
  await page.getByText('查看项目进度', { exact: true }).waitFor()
  const resourceLinks = workSidebar(page).getByRole('navigation', { name: '资源与工具', exact: true })
  const resourceMenu = page.getByRole('navigation', { name: '更多', exact: true })
  const composer = page.locator('.cm-content')
  await composer.fill('折叠侧栏时保留这份草稿')
  await workSidebar(page).getByRole('button', { name: '收起主菜单' }).press('Enter')
  await workSidebar(page).getByRole('button', { name: '展开主菜单' }).waitFor()
  assert.equal((await workSidebar(page).boundingBox()).width, 58)
  await page.locator('#workspace-history').waitFor({ state: 'hidden' })
  await workSidebar(page).getByRole('button', { name: '更多', exact: true }).click()
  await resourceMenu.waitFor()
  await page.keyboard.press('Escape')
  await resourceMenu.waitFor({ state: 'hidden' })
  await resourceLinks.getByRole('link', { name: '技能市场', exact: true }).click()
  await page.waitForURL('**/workspace/skills?session=10')
  assert.equal(await adminSidebar(page).count(), 0)
  assert.equal(await workSidebar(page).getByText(session.title, { exact: true }).count(), 1)
  assert.equal((await workSidebar(page).boundingBox()).width, 58)
  await workSidebar(page).getByRole('button', { name: '展开主菜单' }).press('Enter')
  await workSidebar(page).getByRole('button', { name: '收起主菜单' }).waitFor()
  assert.equal((await workSidebar(page).boundingBox()).width, 260)
  await workSidebar(page).getByText(session.title, { exact: true }).click()
  await page.waitForURL('**/workspace/chat?session=10')
  await page.getByText('查看项目进度', { exact: true }).waitFor()
  assert.equal(await composer.innerText(), '折叠侧栏时保留这份草稿')
  await composer.fill('')
  await workSidebar(page).getByRole('button', { name: '新建对话', exact: true }).click()
  await page.waitForURL('**/workspace/chat')
  await workSidebar(page).getByRole('button', { name: '打开账户信息' }).click()
  const logout = page.getByRole('button', { name: '退出登录' })
  await logout.waitFor()
  await page.getByRole('heading', { name: '今天，想一起做点什么？', exact: true }).click()
  await logout.waitFor({ state: 'hidden' })
  await page.getByText('登录成功', { exact: true }).waitFor({ state: 'hidden' })
  if (process.env.WORKSPACE_SCREENSHOT_DIR) {
    await page.screenshot({ path: join(process.env.WORKSPACE_SCREENSHOT_DIR, 'aihub-workspace-desktop.png'), animations: 'disabled' })
    await workSidebar(page).getByRole('button', { name: '更多', exact: true }).click()
    await resourceMenu.waitFor()
    await page.waitForFunction(() => {
      const popover = document.querySelector('.workspace-resource-popover')
      return popover && getComputedStyle(popover).opacity === '1'
    })
    await page.screenshot({ path: join(process.env.WORKSPACE_SCREENSHOT_DIR, 'aihub-workspace-resources.png'), animations: 'disabled' })
    await page.keyboard.press('Escape')
    await resourceMenu.waitFor({ state: 'hidden' })
  }

  await workSidebar(page).getByRole('button', { name: '收起主菜单' }).click()
  await page.reload()
  await workSidebar(page).getByRole('button', { name: '展开主菜单' }).waitFor()
  assert.equal((await workSidebar(page).boundingBox()).width, 58)
  if (process.env.WORKSPACE_SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.WORKSPACE_SCREENSHOT_DIR, 'aihub-workspace-collapsed.png'), animations: 'disabled' })
  const modeSwitch = page.getByRole('navigation', { name: '产品模式切换' })
  assert.equal(await page.locator('.shell-brand').count(), 0, 'Collapsed header shows mode icons instead of the brand')
  assert.equal(await modeSwitch.getByRole('link').count(), 2)
  assert.equal(await modeSwitch.locator('[aria-current="page"]').getAttribute('aria-label'), '进入工作台')
  assert.equal(await modeSwitch.locator('[aria-current="page"]').evaluate(node => getComputedStyle(node).color), 'rgb(64, 158, 255)')
  await modeSwitch.getByRole('link', { name: '进入管理后台', exact: true }).press('Enter')
  await page.waitForURL('**/admin/skills')
  await adminSidebar(page).getByRole('button', { name: '展开主菜单' }).waitFor()
  assert.equal((await adminSidebar(page).boundingBox()).width, 58)
  assert.equal(await modeSwitch.locator('[aria-current="page"]').getAttribute('aria-label'), '进入管理后台')
  assert.equal(await modeSwitch.locator('[aria-current="page"]').evaluate(node => getComputedStyle(node).color), 'rgb(64, 158, 255)')
  if (process.env.WORKSPACE_SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.WORKSPACE_SCREENSHOT_DIR, 'aihub-admin-collapsed.png'), animations: 'disabled' })
  await modeSwitch.getByRole('link', { name: '进入工作台', exact: true }).click()
  await page.waitForURL('**/workspace/chat')
  await workSidebar(page).getByRole('button', { name: '展开主菜单' }).waitFor()
  assert.equal((await workSidebar(page).boundingBox()).width, 58)
  await page.setViewportSize({ width: 390, height: 744 })
  await page.getByRole('button', { name: '打开工作台导航' }).click()
  await workSidebar(page).getByText(session.title, { exact: true }).waitFor()
  assert.ok((await workSidebar(page).boundingBox()).width > 58, 'Mobile drawer opens fully despite the desktop collapsed preference')
  await workSidebar(page).getByRole('button', { name: '收起主菜单' }).click()
  await workSidebar(page).waitFor({ state: 'hidden' })
  await page.setViewportSize({ width: 1440, height: 900 })
  await workSidebar(page).getByRole('button', { name: '展开主菜单' }).click()
  const workspaceWidth = (await workSidebar(page).boundingBox()).width
  const workspaceBrand = await page.locator('.shell-brand').boundingBox()
  const workspaceAccount = await page.locator('.account-trigger').boundingBox()
  assert.equal(await page.locator('.account-chevron').count(), 0)
  assert.equal(await resourceLinks.evaluate(node => getComputedStyle(node).borderTopWidth), '0px')
  await workSidebar(page).getByRole('link', { name: '管理后台' }).click()
  await page.waitForURL('**/admin/skills')
  await adminSidebar(page).waitFor()
  assert.equal(await page.locator('.workspace-sidebar').count(), 0)
  assert.equal(await page.locator('.account-chevron').count(), 0)
  assert.equal(await page.locator('#management-navigation').evaluate(node => getComputedStyle(node).borderTopWidth), '0px')
  assert.equal((await adminSidebar(page).boundingBox()).width, workspaceWidth)
  const adminBrand = await page.locator('.shell-brand').boundingBox()
  assert.equal(adminBrand.x, workspaceBrand.x)
  assert.equal(adminBrand.y, workspaceBrand.y)
  assert.equal(adminBrand.height, workspaceBrand.height)
  const adminAccount = await page.locator('.account-trigger').boundingBox()
  assert.equal(adminAccount.y, workspaceAccount.y)
  assert.equal(adminAccount.height, workspaceAccount.height)
  const collapse = adminSidebar(page).getByRole('button', { name: '收起主菜单' })
  assert.ok((await collapse.boundingBox()).y > 800, 'Collapse control belongs beside the bottom account row')
  if (process.env.WORKSPACE_SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.WORKSPACE_SCREENSHOT_DIR, 'aihub-admin-desktop.png'), animations: 'disabled' })
  await collapse.click()
  await page.reload()
  await adminSidebar(page).getByRole('button', { name: '展开主菜单' }).waitFor()
  assert.equal(await page.evaluate(() => localStorage.getItem('aihub:sidebar-collapsed')), 'true')
  await adminSidebar(page).getByRole('button', { name: '展开主菜单' }).click()
  await adminSidebar(page).getByRole('link', { name: '进入工作台', exact: true }).click()
  await page.waitForURL('**/workspace/chat')
  await page.goto(base + '/login')
  await page.waitForURL('**/workspace/chat')
  await page.goto(base + '/admin/chat?session=10#legacy')
  await page.waitForURL('**/workspace/chat?session=10#legacy')
  await page.getByText('查看项目进度', { exact: true }).waitFor()
  await page.goto(base + '/admin/workspace/skills?agent=7#legacy')
  await page.waitForURL('**/workspace/skills?agent=7#legacy')
  await workSidebar(page).waitFor()
  assert.equal(await adminSidebar(page).count(), 0)

  const mobile = await setupPage({ width: 390, height: 744 })
  await mobile.goto(base + '/admin/mcp')
  await mobile.waitForURL('**/login')
  await mobile.goto(callback)
  await mobile.waitForURL('**/admin/mcp')
  await mobile.getByRole('button', { name: '打开主菜单' }).click()
  await adminSidebar(mobile).getByRole('link', { name: '进入工作台', exact: true }).click()
  await mobile.waitForURL('**/workspace/chat')
  const menu = mobile.getByRole('button', { name: '打开工作台导航' })
  await menu.click()
  await workSidebar(mobile).getByText(session.title, { exact: true }).waitFor()
  assert.equal(await adminSidebar(mobile).count(), 0)
  assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await mobile.getByText('登录成功', { exact: true }).waitFor({ state: 'hidden' })
  if (process.env.WORKSPACE_SCREENSHOT_DIR) await mobile.screenshot({ path: join(process.env.WORKSPACE_SCREENSHOT_DIR, 'aihub-workspace-mobile.png'), animations: 'disabled' })
  await mobile.getByRole('navigation', { name: '资源与工具', exact: true }).getByRole('link', { name: '连接器', exact: true }).click()
  await mobile.waitForURL('**/workspace/connectors')
  await workSidebar(mobile).waitFor({ state: 'hidden' })
  await menu.click()
  await mobile.keyboard.press('Escape')
  await workSidebar(mobile).waitFor({ state: 'hidden' })
  assert.equal(await menu.evaluate(node => node === document.activeElement), true)
  await menu.click()
  await workSidebar(mobile).getByRole('link', { name: '管理后台' }).click()
  await mobile.waitForURL('**/admin/skills')
  assert.equal(await mobile.locator('.workspace-sidebar').count(), 0)
  assert.deepEqual(errors, [])
  console.log('Passed: OAuth login and deep-link return, exclusive layouts, both switch entries, sidebar preference, session history, legacy links, and mobile drawer.')
} finally {
  await browser.close()
}
