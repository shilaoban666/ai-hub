import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.USAGE_TEST_URL || 'http://localhost:15173'
const output = path.resolve('node_modules/.cache/credit-settlement-browser')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const errors = []
const requests = []
let bulkFails = false
let recoveryMode = 'settled'
const recoveryRequests = []
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'usage-test-only'))
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
const summary = {
  consumed_points: '36.75', claimed_points: '300.00', available_balance: '263.25', reserved_balance: '100.00',
  initial_claim_points: '200.00', daily_claim_points: '100.00', adjustment_added: '20.00', adjustment_deducted: '5.00',
  run_count: 33, active_users: 2, reserved_runs: 1, pending_runs: 1,
}
const runs = Array.from({ length: 33 }, (_, index) => ({
  run_id: `run-${index + 1}`, user_id: 7, session_title: `Conversation ${index + 1}`, model_name: 'Platform Model',
  recorded_at: '2026-09-08T02:00:00Z', created_at: '2026-09-08T01:00:00Z',
  charged_points: index === 0 ? null : '1.23', reserved_points: '100.00',
  settlement_status: index === 0 ? 'pending_reconciliation' : 'settled', status: index === 1 ? 'failed' : 'succeeded',
  source: 'web',
}))
runs[2].status = 'running'
runs[2].settlement_status = 'reserved'
runs.forEach((run, index) => {
  run.settlement_status = 'pending_reconciliation'
  run.billing_mode = index === 0 ? 'reservation' : 'realtime'
})
await page.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  requests.push(url)
  let body = {}
  let status = 200
  if (url.pathname.endsWith('/me') && url.pathname.includes('/iam/')) {
    body = { id: 7, username: 'Example', first_name: 'Example', is_superuser: true, permissions: [] }
  } else if (url.pathname === '/iam/api/users/') {
    const users = [{ id: 7, username: 'zhangsan', first_name: '张三' }, { id: 8, username: 'lisi', first_name: '' }]
    const ids = url.searchParams.get('ids')?.split(',').map(Number)
    const search = url.searchParams.get('search') || ''
    const items = users.filter(user => (!ids || ids.includes(user.id)) && `${user.first_name} ${user.username}`.includes(search))
    body = { total: items.length, items }
  } else if (url.pathname.endsWith('/credits/me')) {
    body = { available_balance: 263.25, display_name: '积分', claimed_today: true }
  } else if (url.pathname.includes('credit-usage')) {
    const skip = Number(url.searchParams.get('skip') || 0)
    const limit = Number(url.searchParams.get('limit') || 16)
    if (url.pathname.endsWith('/runs/settle-all')) {
      assert.equal(route.request().method(), 'POST')
      recoveryRequests.push(url)
      await new Promise(resolve => setTimeout(resolve, 250))
      if (bulkFails) { status = 500; body = { detail: '结算服务暂不可用' } }
      else {
        const pending = runs.filter(run => run.status !== 'running' && run.settlement_status !== 'settled')
        pending.forEach(run => { run.settlement_status = 'settled'; run.charged_points = '3.00' })
        body = { total: pending.length + 1, settled: pending.length, skipped: 1, failed: 0, errors: [] }
      }
    } else if (url.pathname.endsWith('/recover')) {
      assert.equal(route.request().method(), 'POST')
      recoveryRequests.push(url)
      const run = runs.find(item => url.pathname.endsWith(`/runs/${item.run_id}/recover`))
      assert(run)
      if (recoveryMode === 'active') {
        status = 409
        body = { detail: '该对话仍在执行，请先在对话中停止；执行进程失联后可恢复' }
      } else {
        run.status = 'cancelled'
        run.settlement_status = recoveryMode
        run.charged_points = recoveryMode === 'settled' ? '3.00' : null
        body = run
      }
    } else if (url.pathname.endsWith('/runs')) {
      const filtered = url.searchParams.get('status') === 'pending_reconciliation' ? runs.slice(0, 1) : runs
      body = { total: filtered.length, items: filtered.slice(skip, skip + limit) }
    } else if (url.pathname.endsWith('/ledger')) {
      body = { total: 1, items: [{ id: 1, user_id: 7, created_at: '2026-09-08T02:00:00Z', entry_type: 'run_settlement', amount: '98.77', available_after: '263.25', reserved_after: '0.00' }] }
    } else if (url.pathname.endsWith('/users')) {
      body = { total: 2, items: [{ user_id: 7, consumed_points: '36.75', run_count: 33 }, { user_id: 8, consumed_points: '20.00', run_count: 12 }] }
    } else {
      body = { summary, trend: Array.from({ length: 7 }, (_, index) => ({ bucket: `2026-09-0${index + 2}T00:00:00+08:00`, consumed_points: index * 1.75, claimed_points: index % 2 ? 100 : 0 })), models: [{ model_id: 1, model_name: 'Platform Model', consumed_points: '36.75', run_count: 33 }] }
    }

  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

const rowFor = index => page.locator('.credit-usage .el-table__body tbody tr').filter({ has: page.getByText(`Conversation ${index}`, { exact: true }) }).first()
const dialog = () => page.getByRole('dialog')
const checkTabUnderline = async () => {
  const heading = page.locator('.credit-detail-heading')
  const headingBox = await heading.boundingBox()
  const lineBox = await heading.locator('.el-tabs__nav-wrap').boundingBox()
  assert(Math.abs(lineBox.width - headingBox.width) < 1, 'Tab underline must span the full heading width')
  assert.equal(await heading.locator(':scope > .el-button').evaluate(element => getComputedStyle(element).position), 'absolute')
}
try {
  await page.goto(`${baseURL}/admin/dashboard/personal/credit-usage`)
  const bulkButton = page.locator('.credit-detail-heading').getByRole('button', { name: '全量结算', exact: true })
  await bulkButton.waitFor()
  assert.equal(await page.getByRole('button', { name: '全量结算', exact: true }).count(), 1)
  assert.equal(await page.locator('.credit-heading .el-button').count(), 0)
  assert.equal(await page.locator('.credit-detail-heading').getByRole('button', { name: '强制结算', exact: true }).count(), 0)
  const tabBox = await page.getByRole('tab', { name: '消费明细', exact: true }).boundingBox()
  const buttonBox = await bulkButton.boundingBox()
  assert(buttonBox.x > tabBox.x + tabBox.width)
  assert(Math.abs(buttonBox.y - tabBox.y) < 12)
  await checkTabUnderline()
  await page.getByRole('tab', { name: '收支流水', exact: true }).click()
  assert.equal(await bulkButton.count(), 0)
  await page.getByRole('tab', { name: '消费明细', exact: true }).click()
  await rowFor(1).getByRole('button', { name: '强制结算', exact: true }).waitFor()
  await page.screenshot({ path: path.join(output, 'personal-actions.png'), fullPage: true, animations: 'disabled' })
  recoveryMode = 'pending_reconciliation'
  await rowFor(1).getByRole('button', { name: '重试结算', exact: true }).click()
  await dialog().getByRole('button', { name: '重试结算', exact: true }).click()
  await page.getByText('对话已结束，用量记录尚不完整，用量保留待对账', { exact: true }).waitFor()
  await rowFor(1).getByRole('button', { name: '强制结算', exact: true }).click()
  await dialog().getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(recoveryRequests.length, 1)
  recoveryMode = 'settled'
  await rowFor(1).getByRole('button', { name: '强制结算', exact: true }).click()
  await dialog().getByRole('button', { name: '确认结算', exact: true }).click()
  await page.getByText('已按记录用量强制结算', { exact: true }).waitFor()
  assert.equal(recoveryRequests.at(-1).searchParams.get('force_settle'), 'true')
  assert(!recoveryRequests.at(-1).searchParams.has('force_release'))
  await rowFor(2).getByRole('button', { name: '强制结算', exact: true }).click()
  await dialog().getByRole('button', { name: '确认结算', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.credit-run-actions .el-button--warning').length === 13)
  assert.equal(await rowFor(3).getByRole('button', { name: '强制结算', exact: true }).count(), 0)
  await page.getByRole('button', { name: '全量结算', exact: true }).click()
  await dialog().getByText(/不受日期、状态筛选和分页限制/).waitFor()
  await dialog().getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(recoveryRequests.length, 3)
  await page.getByRole('button', { name: '全量结算', exact: true }).click()
  await dialog().getByRole('button', { name: '确认全量结算', exact: true }).click()
  assert(await page.getByRole('button', { name: '全量结算', exact: true }).isDisabled())
  await page.getByText('全量结算完成：已结算 30 条，跳过 1 条，失败 0 条', { exact: true }).waitFor()
  assert(runs.slice(16).every(run => run.settlement_status === 'settled'))
  assert.equal(runs[2].settlement_status, 'pending_reconciliation')
  await page.screenshot({ path: path.join(output, 'personal.png'), fullPage: true })
  await page.goto(`${baseURL}/admin/dashboard/summary/credit-usage`)
  await page.getByRole('heading', { name: '全局用量 / 积分用量', exact: true }).waitFor()
  await page.locator('.credit-detail-heading').getByRole('button', { name: '全量结算', exact: true }).waitFor()
  await page.getByRole('button', { name: '全量结算', exact: true }).click()
  await dialog().getByText(/全部用户的全部历史/).waitFor()
  await dialog().getByRole('button', { name: '取消', exact: true }).click()
  await page.locator('.user-select').click()
  await page.getByRole('option').filter({ hasText: '张三' }).click()
  await page.getByRole('button', { name: '全量结算', exact: true }).click()
  await dialog().getByText(/当前所选用户的全部历史/).waitFor()
  bulkFails = true
  await dialog().getByRole('button', { name: '确认全量结算', exact: true }).click()
  await page.getByText('结算服务暂不可用', { exact: true }).waitFor()
  assert.equal(recoveryRequests.at(-1).searchParams.get('user_id'), '7')
  assert.equal(await page.getByRole('button', { name: '全量结算', exact: true }).isDisabled(), false)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.credit-detail-heading').scrollIntoViewIfNeeded()
  await checkTabUnderline()
  await page.screenshot({ path: path.join(output, 'summary-mobile.png'), fullPage: true, animations: 'disabled' })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
  assert.deepEqual(errors, [])
  console.log('Credit settlement browser checks passed: retry to force settlement, cancellation, realtime, bulk beyond page, active skip, user scope, failure recovery, mobile.')
  console.log(`Screenshots: ${output}`)
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  console.error({ errors, body: (await page.locator('body').innerText()).slice(-2500) })
  throw error
} finally {
  await context.close()
  await browser.close()
}
