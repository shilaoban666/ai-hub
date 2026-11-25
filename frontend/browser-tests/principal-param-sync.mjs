import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.PRINCIPAL_TEST_URL || 'http://localhost:15176'
const output = path.resolve('node_modules/.cache/principal-param-sync')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'principal-test-only'))
const page = await context.newPage()
const errors = []
const writes = []
let failCandidates = false
let failSync = false
let noApis = false
const bound = new Set([101])
const principal = { id: 1, name_cn: 'SKU', name_en: 'sku', type: 1 }
const params = [
  { id: 101, name: 's_sku', display_name: 'SKU' },
  { id: 102, name: 'i_stock_quantity', display_name: '库存数量' },
  { id: 103, name: 's_supplier_name', display_name: '供应商名称' },
]
const apis = [
  { id: 12, name: '库存查询', method: 'GET', path: '/inventory/stock', create_time: '2026-09-08T10:00:00', params },
  { id: 10, name: '商品查询', method: 'POST', path: '/products/search', create_time: '2026-09-07T09:00:00', params: params.slice(0, 2) },
  { id: 9, name: '历史接口', method: 'GET', path: '/history', create_time: null, params: [] },
  ...Array.from({ length: 4 }, (_, index) => ({
    id: 8 - index, name: `业务接口 ${index + 1}`, method: 'GET', path: `/business/${index + 1}`,
    create_time: null,
    params: [params[0], ...Array.from({ length: 12 }, (_, paramIndex) => ({
      id: 200 + index * 12 + paramIndex, name: `s_business_attribute_${paramIndex + 1}`,
      display_name: `业务属性 ${paramIndex + 1}`,
    }))],
  })),
]
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request()
  const url = new URL(request.url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = {}
  let status = 200
  if (request.method() !== 'GET') writes.push({ path: url.pathname, body: request.postDataJSON() })
  if (url.pathname.endsWith('/me') && url.pathname.includes('/iam/')) {
    body = { id: 7, username: 'Example', is_superuser: true, permissions: [] }
  } else if (url.pathname.endsWith('/sync-candidates')) {
    if (failCandidates) { status = 500; body = { detail: '候选参数加载失败' } }
    else body = { items: noApis ? [] : apis.map(api => ({ ...api, params: api.params.map(param => ({ ...param, is_bound: bound.has(param.id) })) })) }
  } else if (url.pathname.endsWith('/params/sync')) {
    if (failSync) { status = 500; body = { detail: '同步暂时失败' } }
    else {
      const ids = request.postDataJSON().param_ids.filter(id => !bound.has(id))
      ids.forEach(id => bound.add(id))
      const removed = request.postDataJSON().unbind_param_ids.filter(id => bound.has(id))
      removed.forEach(id => bound.delete(id))
      body = { params_synced: ids.length, params_unbound: removed.length }
    }
  } else if (url.pathname.endsWith('/resources/params')) {
    body = { principal, items: params.filter(param => bound.has(param.id)), filters: { counts: { all: bound.size } } }
  } else if (url.pathname.includes('/resource-order/')) {
    body = { resource_ids: [] }
  } else if (url.pathname.endsWith('/dashboard/principals')) {
    body = { summary: { principal_count: 1, param_count: bound.size }, total: 1, items: [{ ...principal, param_count: bound.size }] }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

const openDialog = async () => {
  await page.getByRole('button', { name: '从接口同步参数', exact: true }).click()
  await page.getByRole('dialog', { name: '从接口同步参数', exact: true }).waitFor()
}
const dialog = page.getByRole('dialog', { name: '从接口同步参数', exact: true })
const submit = dialog.getByRole('button', { name: '保存绑定变更', exact: true })
const stock = dialog.getByRole('checkbox', { name: /库存数量/ })
const stockLabels = dialog.locator('.el-checkbox').filter({ hasText: '库存数量' })
const sku = dialog.locator('.sync-api-params').getByRole('checkbox', { name: /^SKU / })
const skuLabels = dialog.locator('.sync-api-params .el-checkbox').filter({ hasText: 's_sku' })
const addedTags = dialog.locator('.sync-change-added .el-tag')
const removedTags = dialog.locator('.sync-change-removed .el-tag')
try {
  await page.goto(`${baseURL}/admin/dashboard/summary/principal/1/params`)
  await page.getByRole('heading', { name: '属性', exact: true }).waitFor()
  await openDialog()
  await stockLabels.first().waitFor()
  assert.deepEqual(await dialog.locator('.sync-api-title strong').allTextContents(), apis.map(api => api.name))
  assert.equal(await submit.isDisabled(), true)
  for (const checkbox of await dialog.getByRole('checkbox', { name: /已绑定/ }).all()) {
    assert.equal(await checkbox.isChecked(), true)
    assert.equal(await checkbox.isDisabled(), false)
  }
  assert.equal(await addedTags.count(), 0)
  assert.equal(await removedTags.count(), 0)
  await dialog.locator('.sync-selection-toolbar .el-checkbox').click()
  await dialog.getByText('本次变更 50 项', { exact: true }).waitFor()
  assert.equal(await addedTags.count(), 50)
  assert.equal(await removedTags.count(), 0)
  await dialog.locator('.sync-selection-toolbar .el-checkbox').click()
  await dialog.getByText('本次变更 1 项', { exact: true }).waitFor()
  assert.equal(await addedTags.count(), 0)
  assert.equal(await removedTags.count(), 1)
  await skuLabels.first().click()
  assert.equal(await removedTags.count(), 0)
  await stockLabels.first().click()
  assert.equal(await stock.last().isChecked(), true)
  await dialog.getByText('本次变更 1 项', { exact: true }).waitFor()
  assert.equal(await addedTags.count(), 1)
  await stockLabels.last().click()
  assert.equal(await stock.first().isChecked(), false)
  assert.equal(await addedTags.count(), 0)
  await stockLabels.first().click()
  await skuLabels.first().click()
  assert.equal(await removedTags.count(), 1)
  assert((await dialog.locator('.sync-api-section').first().boundingBox()).height < 100)
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(writes.length, 0)
  assert.deepEqual([...bound], [101])

  await openDialog()
  await stockLabels.first().waitFor()
  assert.equal(await stock.first().isChecked(), false)
  assert.equal(await addedTags.count(), 0)
  assert.equal(await removedTags.count(), 0)
  assert.equal(await sku.first().isChecked(), true)
  await stockLabels.first().click()
  await skuLabels.first().click()
  await dialog.locator('.sync-params-pagination .el-select__wrapper').click()
  await page.getByRole('option', { name: '5 个接口 / 页', exact: true }).click()
  assert.equal(await dialog.locator('.sync-api-section').count(), 5)
  await dialog.locator('.sync-params-pagination .btn-next').click()
  assert.deepEqual(await dialog.locator('.sync-api-title strong').allTextContents(), ['业务接口 3', '业务接口 4'])
  for (const checkbox of await sku.all()) assert.equal(await checkbox.isChecked(), false)
  const secondPageParam = dialog.locator('.sync-api-params').getByRole('checkbox', { name: /业务属性 1 s_business_attribute_1$/ }).first()
  await dialog.locator('.sync-api-params .el-checkbox').filter({ hasText: /^业务属性 1s_business_attribute_1$/ }).first().click()
  assert.equal(await secondPageParam.isChecked(), true)
  await dialog.getByText('本次变更 3 项', { exact: true }).waitFor()
  assert.equal(await addedTags.count(), 2)
  assert.equal(await removedTags.count(), 1)
  await dialog.locator('.sync-params-pagination .btn-prev').click()
  assert.equal(await stock.first().isChecked(), true)
  await dialog.locator('.sync-params-pagination .btn-next').click()
  assert.equal(await secondPageParam.isChecked(), true)
  await dialog.locator('.sync-params-pagination .el-select__wrapper').click()
  await page.getByRole('option', { name: '10 个接口 / 页', exact: true }).click()
  assert.equal(await dialog.locator('.sync-api-section').count(), 7)
  assert.equal(await stock.first().isChecked(), true)
  failSync = true
  await submit.click()
  await page.getByText('同步暂时失败', { exact: true }).waitFor()
  assert.equal(await stock.first().isChecked(), true)
  failSync = false
  await submit.click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(writes.map(write => write.body), [
    { param_ids: [102, 224], unbind_param_ids: [101] },
    { param_ids: [102, 224], unbind_param_ids: [101] },
  ])
  assert.equal(writes.every(write => write.path.endsWith('/params/sync')), true)
  assert.deepEqual([...bound], [102, 224])

  await openDialog()
  await stockLabels.first().waitFor()
  assert.equal(await stock.first().isDisabled(), false)
  assert.equal(await stock.first().isChecked(), true)
  assert.equal(await sku.first().isChecked(), false)
  assert.equal(await addedTags.count(), 0)
  assert.equal(await removedTags.count(), 0)
  await stockLabels.first().click()
  assert.equal(await removedTags.count(), 1)
  assert.equal(await submit.isDisabled(), false)
  await skuLabels.first().click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.el-message').first().waitFor({ state: 'hidden' })
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true, animations: 'disabled' })
  const bounds = await dialog.boundingBox()
  assert(bounds.x >= 0 && bounds.x + bounds.width <= 390)
  assert.equal(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth), true)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()

  await openDialog()
  await stockLabels.first().waitFor()
  assert.equal(await addedTags.count(), 0)
  assert.equal(await removedTags.count(), 0)
  await stockLabels.first().click()
  await submit.click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(writes.at(-1).body, { param_ids: [], unbind_param_ids: [102] })
  assert.deepEqual([...bound], [224])

  failCandidates = true
  await openDialog()
  await dialog.getByText('候选参数加载失败', { exact: true }).waitFor()
  assert.equal(await submit.isDisabled(), true)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  failCandidates = false
  noApis = true
  await openDialog()
  await dialog.getByText('暂无关联接口', { exact: true }).waitFor()
  assert.equal(await submit.isDisabled(), true)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`${baseURL}/admin/dashboard/summary/principal`)
  await page.getByText('属性数量', { exact: true }).waitFor()
  await page.locator('.nav-label').filter({ hasText: '属性' }).waitFor()
  assert.equal(await page.getByText('全局参数', { exact: true }).count(), 0)
  assert.equal(writes.length, 3)
  assert.deepEqual(errors, [])
  console.log('Principal parameter sync browser checks passed (desktop/mobile, selection, cancellation, retry, empty/error states).')
} finally {
  await browser.close()
}
