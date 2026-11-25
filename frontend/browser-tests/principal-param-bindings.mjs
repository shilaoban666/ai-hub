import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.PRINCIPAL_TEST_URL || 'http://localhost:15173'
const output = path.resolve('node_modules/.cache/principal-param-bindings')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'principal-test-only'))
const page = await context.newPage()
const errors = []
const writes = []
const principal = { id: 1, name_cn: 'SKU', name_en: 'sku', type: 1 }
const params = Array.from({ length: 125 }, (_, index) => ({
  id: index + 1,
  name: `param_${String(index + 1).padStart(3, '0')}`,
  display_name: index === 124 ? '   ' : `属性${index + 1}`,
}))
let bound = new Set(params.slice(0, 55).map(item => item.id))
let failBindings = false
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request()
  const url = new URL(request.url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = {}
  let status = 200
  if (url.pathname.endsWith('/me') && url.pathname.includes('/iam/')) {
    body = { id: 7, username: 'Example', is_superuser: true, permissions: [] }
  } else if (url.pathname.endsWith('/params/bindings')) {
    if (request.method() === 'PUT') {
      writes.push(request.postDataJSON())
      bound = new Set(request.postDataJSON().resource_ids)
    } else if (failBindings) {
      status = 500
      body = { detail: '加载绑定失败' }
    }
    if (status === 200) body = { resource_ids: [...bound] }
  } else if (url.pathname.endsWith('/params/batch-match')) {
    const values = request.postDataJSON().values
    body = {
      items: params.filter(item => values.includes(item.name)),
      unmatched_values: values.filter(value => !params.some(item => item.name === value)),
    }
  } else if (url.pathname.endsWith('/resources/params')) {
    const keyword = url.searchParams.get('search') || ''
    const bindingStatus = url.searchParams.get('binding_status') || 'all'
    const matching = params.filter(item => !keyword || item.name.includes(keyword))
    const bindingCounts = {
      all: matching.length,
      bound: matching.filter(item => bound.has(item.id)).length,
      unbound: matching.filter(item => !bound.has(item.id)).length,
    }
    let items = matching.filter(item => bindingStatus === 'bound'
      ? bound.has(item.id) : bindingStatus === 'unbound' ? !bound.has(item.id) : true)
    const total = items.length
    if (url.searchParams.get('paginate') !== 'false') {
      const skip = Number(url.searchParams.get('skip') || 0)
      items = items.slice(skip, skip + Number(url.searchParams.get('limit') || 100))
    }
    body = { principal, total, items, filters: { counts: { all: bound.size }, binding_counts: bindingCounts } }
  } else if (url.pathname.includes('/resource-order/')) {
    body = { resource_ids: [] }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

const dialog = page.getByRole('dialog', { name: '管理属性绑定', exact: true })
const rows = dialog.locator('.el-table__body-wrapper tbody tr')
const submit = dialog.getByRole('button', { name: '保存绑定', exact: true })
const allOnPage = dialog.getByRole('checkbox', { name: '全选本页', exact: true })
const setPageSelection = async checked => {
  if (await allOnPage.isChecked() !== checked) await dialog.locator('thead .el-checkbox').click()
}
const search = dialog.getByPlaceholder('搜索参数名、中文名或编码')
const selectTab = label => dialog.getByRole('tab', { name: new RegExp(`^${label}（`) }).click()
const waitCount = async count => {
  await dialog.getByText(`已选 ${count} 项`, { exact: true }).waitFor()
}
const openDialog = async () => {
  await page.getByRole('button', { name: '管理绑定', exact: true }).click()
  await dialog.waitFor()
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('[role="dialog"] button')].find(item => item.textContent.trim() === '保存绑定')
    return button && !button.disabled
  })
}
const paste = text => search.evaluate((input, value) => {
  const clipboardData = new DataTransfer()
  clipboardData.setData('text', value)
  input.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }))
}, text)

try {
  await page.goto(`${baseURL}/admin/dashboard/summary/principal/1/params`)
  await page.getByRole('heading', { name: '属性', exact: true }).waitFor()
  await openDialog()
  assert.deepEqual(await dialog.getByRole('tab').allTextContents(), ['全部（125）', '已绑定（55）', '未绑定（70）'])
  assert.equal(await rows.count(), 50)
  await waitCount(55)

  await selectTab('未绑定')
  await dialog.getByText('param_056', { exact: true }).waitFor()
  assert.equal(await allOnPage.isChecked(), false)
  await setPageSelection(true)
  await waitCount(105)
  // Classification stays stable while editing, allowing batch uncheck on the same page.
  assert.equal(await rows.count(), 50)
  await setPageSelection(false)
  await waitCount(55)
  await setPageSelection(true)
  await dialog.locator('.btn-next').click()
  await dialog.getByText('param_106', { exact: true }).waitFor()
  assert.equal(await rows.count(), 20)
  assert.equal(await rows.last().locator('td').nth(2).innerText(), '无')
  await setPageSelection(true)
  await waitCount(125)
  await selectTab('已绑定')
  await dialog.getByText('param_001', { exact: true }).waitFor()
  assert.equal(await allOnPage.isChecked(), true)
  await setPageSelection(false)
  await waitCount(75)

  // Search and tab changes preserve draft choices on every page.
  await search.fill('param_05')
  await dialog.getByRole('tab', { name: '全部（10）', exact: true }).waitFor()
  assert.equal(await rows.count(), 6)
  await selectTab('未绑定')
  await dialog.getByText('param_056', { exact: true }).waitFor()
  assert.equal(await rows.count(), 4)
  assert.equal(await allOnPage.isChecked(), true)
  await search.fill('does_not_exist')
  await dialog.getByRole('tab', { name: '全部（0）', exact: true }).waitFor()
  assert.equal(await allOnPage.isDisabled(), true)
  await search.fill('')
  await dialog.getByRole('tab', { name: '全部（125）', exact: true }).waitFor()
  await selectTab('全部')
  assert.equal(await dialog.getByRole('checkbox', { name: '选择param_001', exact: true }).isChecked(), false)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(writes.length, 0)
  assert.equal(bound.size, 55)

  await openDialog()
  await waitCount(55)
  await selectTab('已绑定')
  await setPageSelection(false)
  await selectTab('未绑定')
  await setPageSelection(true)
  await submit.click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual([...bound].sort((a, b) => a - b), Array.from({ length: 55 }, (_, index) => index + 51))
  assert.equal(writes.length, 1)

  // Reopening refreshes the saved classification; paste respects the active tab.
  await openDialog()
  await selectTab('已绑定')
  await paste('param_001，param_051，missing')
  await dialog.getByText('未匹配，请检查属性名称是否正确。', { exact: false }).waitFor()
  assert.equal(await rows.count(), 1)
  await waitCount(55)
  await selectTab('全部')
  assert.equal(await rows.count(), 2)
  assert.equal(await dialog.getByRole('checkbox', { name: '选择param_001', exact: true }).isChecked(), false)
  await dialog.getByRole('checkbox', { name: '选择param_001', exact: true }).locator('xpath=ancestor::label').click()
  await waitCount(56)
  await page.screenshot({ path: path.join(output, 'dialog.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()

  failBindings = true
  await page.getByRole('button', { name: '管理绑定', exact: true }).click()
  await page.getByText('加载绑定失败', { exact: true }).waitFor()
  assert.equal(await submit.isDisabled(), true)
  assert.equal(writes.length, 1)
  assert.deepEqual(errors, [])
  console.log('Principal attribute binding tabs: pagination, batch selection, search, paste, save/cancel and load failure passed.')
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser.close()
}
