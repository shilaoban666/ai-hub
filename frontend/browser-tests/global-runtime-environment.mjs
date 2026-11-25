import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'test-only-token'))
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
const endpoint = '/aihub/api/admin/global-settings/runtime-environment'
let variables = {}
let saves = 0
let failLoad = false
await page.route('**/*', async route => {
  const request = route.request()
  const pathname = new URL(request.url()).pathname
  if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
  let body = {}
  let status = 200
  if (pathname.includes('/iam/') && pathname.endsWith('/me')) {
    body = { id: 1, username: 'Admin', is_superuser: true, permissions: [] }
  } else if (pathname === endpoint) {
    if (request.method() === 'PUT') {
      variables = request.postDataJSON().variables
      saves++
    }
    body = failLoad ? { detail: 'Test load failure' } : { variables }
    if (failLoad) status = 503
  } else if (pathname.endsWith('/global-settings')) {
    body = { brand_icon: 'H', brand_name: 'AI Hub', brand_subtitle: '合趣网络' }
  } else if (pathname.endsWith('/credits/me')) {
    body = { available_balance: 0, claimed_today: true }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(`${process.env.GLOBAL_SETTINGS_TEST_URL || 'http://localhost:15173'}/admin/global-settings`)
  const section = page.locator('.environment-section')
  const add = section.getByRole('button', { name: '添加环境变量', exact: true })
  const save = section.getByRole('button', { name: '保存环境变量', exact: true })
  await add.waitFor()
  await page.waitForFunction(() => !document.querySelector('.environment-actions button').disabled)
  assert.equal(await section.locator('.el-empty__description').innerText(), '无')
  assert.equal(await save.isDisabled(), true)
  assert.match(await section.locator('.environment-example').innerText(), /import os\s+token = os.environ\["X_MCP_TOKEN"\]/)
  const addBox = await add.boundingBox()
  const saveBox = await save.boundingBox()
  assert.equal(addBox.y, saveBox.y)
  assert.ok(addBox.x > (await section.boundingBox()).x + 500, 'Add button should be at upper right')
  await add.click()
  await page.getByRole('textbox', { name: '变量名 1', exact: true }).fill('X_MCP_TOKEN')
  await page.getByLabel('变量值 1', { exact: true }).fill('test-only-value')
  await add.click()
  await page.getByRole('textbox', { name: '变量名 2', exact: true }).fill('X_MCP_TOKEN')
  await save.click()
  await page.getByText('变量名 X_MCP_TOKEN 重复，请修改后保存', { exact: true }).waitFor()
  assert.equal(saves, 0)
  await page.getByRole('textbox', { name: '变量名 2', exact: true }).fill('X_MCP_USER')
  await page.getByLabel('变量值 2', { exact: true }).fill('toolbox')
  await save.click()
  await page.waitForFunction(() => document.querySelector('.environment-actions button:last-child').disabled)
  assert.deepEqual(variables, { X_MCP_TOKEN: 'test-only-value', X_MCP_USER: 'toolbox' })
  await page.reload()
  await page.getByRole('textbox', { name: '变量名 1', exact: true }).waitFor()
  assert.equal(await page.getByLabel('变量值 1', { exact: true }).inputValue(), 'test-only-value')
  assert.equal(await page.getByLabel('变量值 1', { exact: true }).getAttribute('type'), 'password')
  await section.scrollIntoViewIfNeeded()
  await page.screenshot({ path: '/tmp/aihub-global-runtime-environment-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await section.scrollIntoViewIfNeeded()
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
  await page.screenshot({ path: '/tmp/aihub-global-runtime-environment-mobile.png', fullPage: true })
  await page.getByRole('button', { name: '删除环境变量 2', exact: true }).click()
  await page.getByRole('button', { name: '删除环境变量 1', exact: true }).click()
  await save.click()
  await page.waitForFunction(() => document.querySelector('.environment-actions button:last-child').disabled)
  assert.deepEqual(variables, {})
  await page.reload()
  await section.locator('.el-empty__description').waitFor()
  assert.equal(await section.locator('.el-empty__description').innerText(), '无')
  failLoad = true
  await page.reload()
  await section.getByText('环境变量加载失败', { exact: true }).waitFor()
  assert.equal(await add.isDisabled(), true)
  failLoad = false
  await section.getByRole('button', { name: '重新加载' }).click()
  await section.locator('.el-empty__description').waitFor()
  assert.deepEqual(errors, [])
  console.log('Global runtime environment: CRUD, duplicate validation, layout, Python example and load recovery passed')
} finally {
  await browser.close()
}
