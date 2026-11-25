import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.EMBED_TEST_URL || 'http://localhost:15176'
const output = path.resolve('node_modules/.cache/embed-browser')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const errors = []
const sent = []
const authActions = []
let businessLoggedIn = false
let releaseResponse
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.pathname === '/func_process_app/aihub_embed_auth/') {
    const request = route.request().postDataJSON()
    authActions.push(request.action)
    return route.fulfill({ status: businessLoggedIn ? 200 : 401, contentType: 'application/json', body: JSON.stringify(businessLoggedIn ? { code: 0, data: { user_id: 7, session_id: 'a'.repeat(64), ...(request.action === 'authorize' ? { access_token: 'embed-test-only', token_type: 'bearer', expires_in: 900 } : {}) } } : { code: -1, msg: '请先登录 fancyqube' }) })
  }
  if (url.pathname === '/embed-test-host') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><title>订单管理</title></head><body style="margin:0;background:#f5f6f7;font-family:Arial"><header style="padding:22px;border-bottom:1px solid #ddd;background:white">fancyqube</header><main style="padding:24px"><h2>订单管理</h2></main><script src="/embed/assistant.js"></script></body></html>` })
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: 'embed-test', permissions: [] }
  if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
  if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, display_name: '算点', available_balance: 100 }
  if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
  if (url.pathname === '/aihub/api/agents/1/sessions') body = { total: 1, items: [{ id: 3, title: '历史对话', message_count: 0, model_id: 1 }] }
  if (url.pathname.endsWith('/share')) body = { token: route.request().method() === 'POST' ? 'browser-share-test' : null }
  if (url.pathname === '/aihub/api/agents/1/messages' && route.request().method() === 'POST') {
    sent.push(route.request().postDataJSON())
    await new Promise(resolve => { releaseResponse = resolve })
    return route.fulfill({ contentType: 'text/event-stream', body: [
      { type: 'run_start', run_id: 'test-run', session_id: 3 },
      { type: 'text', content: '已收到当前页面。这是浏览器测试响应。' },
      { type: 'turn_metrics', duration_ms: 21000, charged_points: 0.37, usage: { input_tokens: 39993, output_tokens: 878, cache_read_input_tokens: 73728, cache_creation_input_tokens: 0 } },
      { type: 'done' },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
  }
  return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(`${base}/embed-test-host?id=12&token=secret`)
  const launcher = page.getByRole('button', { name: '打开 AI 助手', exact: true })
  await launcher.locator('svg').waitFor()
  const launcherBounds = await launcher.boundingBox()
  assert.equal(await launcher.locator('.spirit-motion').evaluate(el => getComputedStyle(el).animationName), 'none', 'The desk stays planted')
  assert.deepEqual(await launcher.boundingBox(), launcherBounds)
  await launcher.screenshot({ path: path.join(output, 'launcher.png'), animations: 'disabled' })
  await launcher.hover()
  assert(await launcher.evaluate(el => el.classList.contains('attentive')))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await launcher.locator('.spirit-motion').evaluate(image => getComputedStyle(image).animationName), 'none')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await launcher.screenshot({ path: path.join(output, 'launcher-hover.png'), animations: 'disabled' })
  await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
  const chat = page.frameLocator('iframe[title="AI Hub 对话"]')
  await chat.getByRole('button', { name: '重试', exact: true }).waitFor()
  await chat.locator('.embed-page-context').getByText('订单管理', { exact: true }).waitFor()
  assert.equal(await chat.locator('.embed-page-context').getAttribute('title'), null)
  await chat.locator('.embed-page-context').getByText('订单管理', { exact: true }).hover()
  const pageUrlTooltip = chat.getByRole('tooltip').filter({ hasText: `${base}/embed-test-host?id=12` })
  await pageUrlTooltip.waitFor({ state: 'visible' })
  await chat.locator('.embed-page-context .el-switch').hover()
  await chat.getByRole('tooltip').filter({ hasText: '对话中附带当前页面信息（标题和 URL）' }).waitFor({ state: 'visible' })
  await pageUrlTooltip.waitFor({ state: 'hidden' })
  await page.screenshot({ path: path.join(output, 'login-desktop.png') })
  businessLoggedIn = true
  authActions.length = 0
  await chat.getByRole('button', { name: '重试', exact: true }).click()
  await chat.getByPlaceholder('输入问题或任务').waitFor()
  assert.deepEqual(authActions, ['status', 'authorize', 'status'], 'Bootstrap API requests must reuse the initial identity check')
  await chat.getByRole('button', { name: '查看算点余额', exact: true }).waitFor()
  const assertToolbarAlignment = async () => {
    const outer = page.locator('#aihub-assistant-root').locator('header button')
    const inner = chat.locator('.embed-chat-actions button')
    assert.equal(await outer.count(), 3)
    assert.equal(await inner.count(), 3)
    for (let index = 0; index < 3; index++) {
      const top = await outer.nth(index).boundingBox()
      const bottom = await inner.nth(index).boundingBox()
      assert(Math.abs(top.x + top.width / 2 - bottom.x - bottom.width / 2) <= 1, `Toolbar column ${index + 1} should align`)
    }
  }
  await assertToolbarAlignment()
  await chat.getByRole('button', { name: '查看算点余额', exact: true }).hover()
  await chat.getByRole('tooltip').getByText('算点余额 100').waitFor()
  const newButton = await chat.getByRole('button', { name: '新对话', exact: true }).boundingBox()
  const titleBox = await chat.locator('.mobile-chat-title').boundingBox()
  assert(newButton.x + newButton.width <= titleBox.x)
  assert(await chat.getByRole('button', { name: '分享当前对话', exact: true }).isDisabled())
  await page.locator('#aihub-assistant-root').locator('header img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  await page.screenshot({ path: path.join(output, 'chat-desktop.png'), animations: 'disabled' })
  await chat.getByRole('button', { name: '工作区文件', exact: true }).click()
  await chat.getByRole('button', { name: '收起工作区文件', exact: true }).waitFor()
  await chat.locator('.workspace-panel .el-loading-mask').waitFor({ state: 'hidden' })
  await page.screenshot({ path: path.join(output, 'workspace-desktop.png'), animations: 'disabled' })
  await chat.getByRole('button', { name: '收起工作区文件', exact: true }).click()
  await chat.getByPlaceholder('输入问题或任务').fill('这个页面是什么？')
  await chat.getByRole('button', { name: '发送', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('#aihub-assistant-root').shadowRoot.querySelector('iframe') !== null)
  for (let attempt = 0; !releaseResponse && attempt < 50; attempt++) await new Promise(resolve => setTimeout(resolve, 100))
  assert.equal(sent.length, 1)
  assert.deepEqual(sent[0].page_context, { url: `${base}/embed-test-host?id=12`, title: '订单管理' })
  assert.equal(sent[0].content, '这个页面是什么？')
  const originalFrame = page.frames().find(frame => frame.url().includes('/embed/chat'))
  await page.getByRole('button', { name: '收起助手', exact: true }).click()
  releaseResponse()
  await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
  assert.equal(page.frames().find(frame => frame.url().includes('/embed/chat')), originalFrame)
  await chat.getByText('已收到当前页面。这是浏览器测试响应。', { exact: true }).waitFor()
  const metrics = chat.locator('.turn-metrics').filter({ hasText: 'Token' })
  assert.equal(await metrics.locator('.input-breakdown').isVisible(), false)
  assert((await metrics.getAttribute('title')).includes('缓存输入 73,728'))
  assert(await metrics.evaluate(element => new Set([...element.children].filter(child => child.getClientRects().length).map(child => child.offsetTop)).size === 1))
  await page.screenshot({ path: path.join(output, 'metrics-compact.png'), animations: 'disabled' })
  await page.getByRole('button', { name: '展开面板', exact: true }).click()
  await metrics.locator('.input-breakdown').waitFor({ state: 'visible' })
  await page.screenshot({ path: path.join(output, 'metrics-wide.png'), animations: 'disabled' })
  await page.getByRole('button', { name: '恢复面板宽度', exact: true }).click()
  await metrics.locator('.input-breakdown').waitFor({ state: 'hidden' })
  await chat.getByRole('button', { name: '分享当前对话', exact: true }).click()
  await chat.getByRole('dialog', { name: '分享对话' }).waitFor()
  await chat.getByRole('dialog', { name: '分享对话' }).locator('.el-dialog__headerbtn').click()
  await page.evaluate(() => { document.title = '库存管理'; history.pushState({}, '', '/embed-test-host?page_id=20&password=secret') })
  await chat.locator('.embed-page-context').getByText('库存管理', { exact: true }).waitFor()
  await chat.getByRole('button', { name: '新对话', exact: true }).click()
  assert(new URL(originalFrame.url()).pathname === '/embed/chat')
  await chat.getByRole('button', { name: '打开会话列表', exact: true }).click()
  await chat.getByText('历史对话', { exact: true }).last().click()
  assert(new URL(originalFrame.url()).pathname === '/embed/chat')
  await page.getByRole('button', { name: '展开面板', exact: true }).click()
  await page.screenshot({ path: path.join(output, 'chat-expanded.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await assertToolbarAlignment()
  await page.screenshot({ path: path.join(output, 'chat-mobile.png'), animations: 'disabled' })
  await chat.getByRole('button', { name: '工作区文件', exact: true }).click()
  await chat.getByRole('button', { name: '收起工作区文件', exact: true }).waitFor()
  await chat.locator('.workspace-panel .el-loading-mask').waitFor({ state: 'hidden' })
  await page.screenshot({ path: path.join(output, 'workspace-mobile.png'), animations: 'disabled' })
  await chat.getByRole('button', { name: '收起工作区文件', exact: true }).click()
  assert(await chat.locator('body').evaluate(element => element.scrollWidth <= innerWidth))
  await chat.locator('.embed-page-context .el-switch').click()
  await chat.getByPlaceholder('输入问题或任务').fill('不带页面信息')
  releaseResponse = null
  await chat.getByRole('button', { name: '发送', exact: true }).click()
  for (let attempt = 0; !releaseResponse && attempt < 50; attempt++) await new Promise(resolve => setTimeout(resolve, 100))
  assert.equal(sent.at(-1).page_context, null)
  releaseResponse()
  await chat.getByText('已收到当前页面。这是浏览器测试响应。', { exact: true }).waitFor()
  assert.deepEqual(errors, [])
  await chat.locator('.text-block').last().evaluate(element => {
    for (let index = 0; index < 80; index++) {
      const paragraph = document.createElement('p')
      paragraph.textContent = `滚动隔离验证 ${index + 1}`
      element.appendChild(paragraph)
    }
  })
  await page.evaluate(() => { document.body.style.minHeight = '4000px' })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await page.evaluate(() => window.scrollTo(0, 300))
    const messages = chat.locator('#chat-messages')
    for (let cycle = 0; cycle < 3; cycle++) {
      await messages.evaluate(element => { element.scrollTop = 200 })
      const frameSize = () => page.locator('iframe[title="AI Hub 对话"]').evaluate(el => [el.clientWidth, el.clientHeight])
      const viewportBefore = await frameSize()
      await page.getByRole('button', { name: '收起助手', exact: true }).click()
      assert.deepEqual(await frameSize(), viewportBefore, 'Closing must preserve the iframe layout box')
      assert(await page.locator('.panel').evaluate(el => el.hasAttribute('inert')), 'Hidden chat must not receive focus or pointer input')
      await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
      assert.equal(await page.locator('.panel').evaluate(el => el.hasAttribute('inert')), false)
      assert.equal(page.frames().find(frame => frame.url().includes('/embed/chat')), originalFrame)
      const before = await messages.evaluate(element => element.scrollTop)
      const box = await messages.boundingBox()
      await page.mouse.move(box.x + box.width / 2, box.y + 50)
      await page.mouse.wheel(0, 250)
      await page.waitForTimeout(300)
      assert(await messages.evaluate(element => element.scrollTop) > before, `Messages must scroll after reopening (${width}px, cycle ${cycle})`)
      assert.equal(await page.evaluate(() => scrollY), 300, 'Reopened chat must not scroll the host')
    }
    await messages.evaluate(element => { element.scrollTop = 200 })
    const bounds = await messages.boundingBox()
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 50)
    await page.mouse.wheel(0, 250)
    await page.waitForTimeout(250)
    assert(await messages.evaluate(element => element.scrollTop > 200), 'Messages should scroll inside the assistant')
    assert.equal(await page.evaluate(() => scrollY), 300)
    for (const direction of [-1, 1]) {
      await messages.evaluate((element, direction) => { element.scrollTop = direction < 0 ? 0 : element.scrollHeight }, direction)
      await page.mouse.wheel(0, direction * 900)
      await page.waitForTimeout(250)
      assert.equal(await page.evaluate(() => scrollY), 300, 'Message boundaries must not scroll the host')
    }
    for (const toolbar of [page.locator('#aihub-assistant-root').locator('header'), chat.locator('.embed-page-context')]) {
      await toolbar.hover()
      await page.mouse.wheel(0, 600)
      await page.waitForTimeout(250)
      assert.equal(await page.evaluate(() => scrollY), 300, 'Assistant toolbars must not scroll the host')
    }
    assert(await chat.locator('html').evaluate(element => element.scrollHeight <= innerHeight), 'The iframe document must not have a second scrollbar')
    await page.screenshot({ path: path.join(output, `scroll-isolation-${width}.png`), animations: 'disabled' })
    if (width === 1440) {
      await page.mouse.move(100, 400)
      await page.mouse.wheel(0, 400)
      await page.waitForTimeout(250)
      assert(await page.evaluate(() => scrollY > 300), 'The business page should still scroll outside the assistant')
    }
  }
  await page.getByRole('button', { name: '收起助手', exact: true }).click()
  await page.waitForTimeout(300)
  const closedCount = authActions.length
  await page.waitForTimeout(16000)
  assert.equal(authActions.length, closedCount, 'Closed assistant must not poll authentication')
  await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
  await page.waitForTimeout(500)
  assert.deepEqual(authActions.slice(closedCount), ['status'], 'Reopening checks identity once without issuing another token')
  const openCount = authActions.length
  await page.waitForTimeout(16000)
  assert.equal(authActions.length, openCount, 'Idle open assistant must not poll authentication')
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await page.waitForTimeout(16000)
  assert.equal(authActions.length, openCount, 'Background page must not poll authentication')
  await page.evaluate(() => {
    delete document.hidden
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await page.waitForTimeout(500)
  assert.deepEqual(authActions.slice(openCount), ['status'], 'Returning to the foreground checks identity once')
  console.log('Embed browser checks passed, including 3-request login, idle/closed/background silence and one status check on resume.')
} finally {
  releaseResponse?.()
  await browser.close()
}
