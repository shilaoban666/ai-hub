import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const output = path.resolve('node_modules/.cache/connector-headers')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const errors = []
const writes = []
let storedHeaders = []
let personalSystemHeaders = []
const row = { id: 51, definition_id: 31, name: 'GitLab', transport_type: 'streamable_http', status: 'active', is_system: false }
const systemRow = { ...row, id: 'system-21', definition_id: 21, name: 'Managed MCP', is_system: true }
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(() => localStorage.setItem('access_token', 'browser-test-only'))
await page.route('**/*', async route => {
  const pathname = new URL(route.request().url()).pathname
  if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
  const method = route.request().method()
  let body = { items: [], total: 0 }
  if (pathname === '/iam/api/me') body = { id: 7, username: 'test', is_superuser: true, permissions: [] }
  if (pathname.endsWith('/assets/mcp/connections')) body = { items: [row, systemRow], total: 2 }
  if (pathname.endsWith('/assets/admin/mcp/definitions')) body = { items: [{ ...row, id: 21 }], total: 1 }
  if (pathname.endsWith('/headers')) {
    const personalSystem = pathname.endsWith('/system/21/headers')
    if (method === 'PUT') {
      const payload = route.request().postDataJSON()
      writes.push({ pathname, payload })
      const headers = Object.keys(payload.headers).map(name => ({ name, configured: true }))
      if (personalSystem) personalSystemHeaders = headers
      else storedHeaders = headers
    }
    body = { headers: personalSystem ? personalSystemHeaders : storedHeaders }
  }
  if (method === 'POST' && pathname.endsWith('/assets/mcp/definitions')) {
    writes.push({ pathname, payload: route.request().postDataJSON() })
    body = { id: 31, name: 'GitLab test', latest_revision: { id: 32 } }
  }
  if (method === 'POST' && pathname.endsWith('/assets/mcp/connections')) body = row
  return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  const base = process.env.CONNECTOR_TEST_URL || 'http://localhost:15176'
  await page.goto(`${base}/admin/workspace/connectors`)
  await page.getByRole('button', { name: '新建连接器', exact: true }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('例如：知识库').fill('GitLab test')
  await dialog.getByPlaceholder('https://mcp.example.com').fill('http://172.26.36.234:3333/mcp')
  await dialog.getByRole('button', { name: '添加 Authorization', exact: true }).click()
  await dialog.getByRole('textbox', { name: '请求头值 1', exact: true }).fill('Bearer create-test')
  assert.equal(await dialog.locator('input[aria-label="请求头值 1"]').getAttribute('type'), 'password')
  await dialog.getByRole('button', { name: '添加', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(writes[0].payload.headers, { Authorization: 'Bearer create-test' })
  const search = page.getByPlaceholder('搜索连接器', { exact: true })
  await search.fill('GitLab')
  await page.getByRole('button', { name: '请求头', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: '添加 Authorization', exact: true }).click()
  assert(await dialog.locator('input[aria-label="请求头值 1"]').evaluate(input => {
    const search = document.querySelector('input[name="connector-search"]')
    return input.form !== null && input.form !== search.form && search.type === 'search'
  }), 'Header credentials must have a separate form from the connector filter')
  await dialog.locator('input[aria-label="请求头值 1"]').fill('Bearer edit-test')
  assert.equal(await search.inputValue(), 'GitLab', 'Editing headers must preserve the connector filter')
  await page.screenshot({ path: path.join(output, 'desktop.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(writes.at(-1).payload.headers, { Authorization: 'Bearer edit-test' })
  assert.equal(await search.inputValue(), 'GitLab')
  assert.equal(await page.getByRole('button', { name: '请求头', exact: true }).count(), 1)
  await page.getByRole('button', { name: '请求头', exact: true }).click()
  await dialog.getByPlaceholder('已配置，留空保留').waitFor()
  assert.equal(await dialog.getByPlaceholder('已配置，留空保留').inputValue(), '')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'mobile.png'), animations: 'disabled' })
  assert(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth))
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(writes.at(-1).payload.headers, { Authorization: null })
  await page.setViewportSize({ width: 1440, height: 960 })
  await search.fill('Managed MCP')
  assert.equal(await page.getByRole('button', { name: '停用', exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: '删除', exact: true }).count(), 0)
  await page.getByRole('button', { name: '请求头', exact: true }).click()
  dialog = page.getByRole('dialog', { name: 'Managed MCP · 个人请求头', exact: true })
  await dialog.getByRole('button', { name: '添加 Authorization', exact: true }).click()
  await dialog.locator('input[aria-label="请求头值 1"]').fill('Bearer personal-system')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert(writes.at(-1).pathname.endsWith('/system/21/headers'))
  assert.deepEqual(writes.at(-1).payload.headers, { Authorization: 'Bearer personal-system' })
  assert.deepEqual(storedHeaders, [{ name: 'Authorization', configured: true }])
  await page.getByRole('button', { name: '请求头', exact: true }).click()
  await dialog.getByPlaceholder('已配置，留空保留').waitFor()
  await page.screenshot({ path: path.join(output, 'personal-system.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: '删除请求头', exact: true }).click()
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(writes.at(-1).payload.headers, {})
  await page.goto(`${base}/admin/workbench-settings?tab=resources`)
  await page.getByRole('button', { name: 'MCP', exact: true }).click()
  await page.getByRole('button', { name: '请求头', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('已配置，留空保留').waitFor()
  await dialog.getByRole('button', { name: '删除请求头', exact: true }).click()
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert(writes.at(-1).pathname.endsWith('/definitions/21/headers'))
  assert.deepEqual(writes.at(-1).payload.headers, {})
  assert.deepEqual(errors, [])
  console.log('Connector browser checks passed: create, edit, masked value, preserve, delete, system MCP, desktop and mobile.')
} finally {
  await browser.close()
}
