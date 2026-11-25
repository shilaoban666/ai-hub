import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.EMBED_TEST_URL || 'http://localhost:15173'
const host = 'http://localhost:10925'
const hostAuthPath = '/api/ai-assistant/auth'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const context = await browser.newContext()
// The fulfilled test host has no real network address; Chromium requires this
// test-context permission before it can load the actual loopback Vite server.
await context.grantPermissions(['local-network-access'], { origin: host })
let userId = 7
let sessionStatus = 200
let exchangeCount = 0
let rejectToken = ''
let workbenchRefreshes = 0
const apiTokens = []
const errors = []
const networkErrors = []
try {
  await context.addInitScript(({ base }) => {
    if (location.origin === base) {
      localStorage.setItem('access_token', 'independent-workbench-user')
      localStorage.setItem('refresh_token', 'independent-workbench-refresh')
    }
  }, { base })
  await context.route('**/*', async route => {
    const req = route.request()
    const url = new URL(req.url())
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': base }, body: JSON.stringify(body) })
    if (url.origin === host && url.pathname === '/embed-sso-test') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<html><head><title>业务页面</title></head><body><script src="${base}/embed/assistant.js" data-aihub-auth-url="${hostAuthPath}" data-aihub-csrf="test-csrf"></script></body></html>` })
    if (url.origin === host && url.pathname === hostAuthPath) {
      assert.equal(req.headers()['x-csrftoken'], 'test-csrf')
      if (sessionStatus !== 200) return json({ code: -1, msg: '请先登录 fancyqube' }, sessionStatus)
      const body = req.postDataJSON()
      const result = { user_id: userId, session_id: String(userId).repeat(64) }
      if (body.action === 'authorize') {
        assert.deepEqual(Object.keys(body).sort(), ['action', 'session_id'])
        assert.equal(body.session_id, result.session_id)
        exchangeCount += 1
        Object.assign(result, { access_token: `embedded-${userId}-${exchangeCount}`, token_type: 'bearer', expires_in: 900 })
      }
      return json({ code: 0, data: result })
    }
    if (url.pathname.startsWith('/o/embed/')) throw new Error('Embedded login must obtain its token from the business backend')
    if (url.pathname === '/o/token/') {
      assert(!req.frame().url().includes('/embed/chat'), 'Embedded login must not use the normal token endpoint')
      const body = new URLSearchParams(req.postData())
      assert.equal(body.get('grant_type'), 'refresh_token')
      assert.equal(body.get('refresh_token'), 'independent-workbench-refresh')
      workbenchRefreshes += 1
      return json({ access_token: 'independent-workbench-renewed', refresh_token: 'independent-workbench-rotated' })
    }
    if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
    const auth = req.headers().authorization
    apiTokens.push(auth)
    const embedded = req.frame().url().includes('/embed/chat')
    if (embedded) assert(auth?.startsWith('Bearer embedded-'), 'Workbench credentials must never be sent by the iframe')
    else if (auth === 'Bearer independent-workbench-user') return json({ detail: 'expired' }, 401)
    if (auth === rejectToken) return json({ detail: 'expired' }, 401)
    const tokenUser = embedded ? Number(auth.split('-')[1]) : 77
    let body = { items: [], total: 0 }
    if (url.pathname === '/iam/api/me') body = { id: tokenUser, username: `user-${tokenUser}`, permissions: [] }
    if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: tokenUser }
    if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100, display_name: '算点' }
    if (/\/agents\/\d+$/.test(url.pathname)) body = { id: tokenUser, name: `助手 ${tokenUser}`, kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
    if (url.pathname.endsWith('/share')) body = { token: null }
    return json(body)
  })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') networkErrors.push(message.text()) })
  page.setDefaultTimeout(12000)
  page.on('requestfailed', request => networkErrors.push(`${request.url()}: ${request.failure()?.errorText}`))
  await page.goto(`${host}/embed-sso-test`)
  await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
  const chat = page.frameLocator('iframe[title="AI Hub 对话"]')
  await chat.getByPlaceholder('输入问题或任务').waitFor()
  assert.equal(exchangeCount, 1, 'First open must silently authenticate once')
  assert.equal(context.pages().length, 1, 'No login tabs or popups')
  const frame = page.frames().find(value => value.url().includes('/embed/chat'))
  assert.deepEqual(await frame.evaluate(() => [localStorage.getItem('access_token'), localStorage.getItem('refresh_token')]), ['independent-workbench-user', 'independent-workbench-refresh'])
  // An existing API receiving 401 uses the new bridge for this iframe only.
  rejectToken = apiTokens[0]
  await frame.evaluate(async () => {
    const { iamRequest } = await import('/src/api/request.js')
    await iamRequest.get('/me')
  })
  assert.equal(exchangeCount, 2)
  userId = 8
  await frame.evaluate(() => window.dispatchEvent(new Event('focus')))
  await chat.getByPlaceholder('输入问题或任务').waitFor({ state: 'visible' })
  await frame.waitForFunction(async () => {
    const { useAuthStore } = await import('/src/stores/auth.js')
    return useAuthStore().user?.id === 8
  })
  assert.equal(exchangeCount, 3, 'Switching the business account must establish a new identity')
  const previousCount = exchangeCount
  sessionStatus = 401
  await frame.evaluate(() => window.dispatchEvent(new Event('focus')))
  await chat.getByText('请先登录 fancyqube', { exact: true }).waitFor()
  assert.equal(await chat.getByPlaceholder('输入问题或任务').count(), 0)
  assert.equal(exchangeCount, previousCount, 'Logout must not silently refresh old credentials')
  assert.deepEqual(await frame.evaluate(() => [localStorage.getItem('access_token'), localStorage.getItem('refresh_token')]), ['independent-workbench-user', 'independent-workbench-refresh'])
  assert.deepEqual(errors, [])
  const workbench = await context.newPage()
  await workbench.goto(`${base}/admin/chat`)
  await workbench.getByPlaceholder('输入问题或任务').waitFor()
  assert.equal(workbenchRefreshes, 1, 'Normal workbench token refresh must continue using the original endpoint')
  assert.equal(await workbench.evaluate(() => localStorage.getItem('access_token')), 'independent-workbench-renewed')
  console.log('Passed: client user-token login, custom host endpoint, no popup, isolated credentials, 401 renewal, account switch and logout.')
} catch (error) {
  console.error({ errors, networkErrors })
  throw error
} finally { await browser.close() }
