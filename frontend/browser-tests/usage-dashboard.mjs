import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.USAGE_TEST_URL || 'http://localhost:15175'
const output = path.resolve('node_modules/.cache/usage-browser')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true })
const errors = []
const requests = []
let tokenUnavailable = false
let isSuperuser = true
let recoveryMode = 'settled'
const recoveryRequests = []
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'usage-test-only'))
const page = await context.newPage()
const usageMenu = name => page.locator('.management-navigation .el-sub-menu').filter({ has: page.locator('.el-sub-menu__title').filter({ hasText: name }) })
const ready = () => page.waitForFunction(() => !Array.from(document.querySelectorAll('.el-loading-mask')).some(element => getComputedStyle(element).display !== 'none'))
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
const tokens = Array.from({ length: 20 }, (_, index) => ({
  id: index + 1, created_at: `2026-09-08T02:00:${String(59 - index).padStart(2, '0')}Z`, api_key_name: `Key ${index + 1}`, model: 'Token Model',
  input_tokens: 1000, output_tokens: 100, cache_tokens: 50, total_tokens: 1150, duration_ms: 1000,
}))
function tokenPayload(userId = 99) {
  return { user: { user_id: userId, username: userId === 99 ? 'Example' : 'Second', email: 'example@test.invalid' }, summary: { total_tokens: 48300, request_count: 42 },
    trend: [], models: [], api_keys: [], endpoints: [], users: [
      { user_id: 99, username: 'Example', total_tokens: 48300, request_count: 42 },
      { user_id: 100, username: 'Second', total_tokens: 20000, request_count: 42 },
    ], recent_requests: tokens }
}
await page.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  requests.push(url)
  let body = {}
  let status = 200
  if (url.pathname.endsWith('/me') && url.pathname.includes('/iam/')) {
    body = { id: 7, username: 'Example', first_name: 'Example', is_superuser: isSuperuser, permissions: [] }
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
    if (url.pathname.endsWith('/recover')) {
      assert.equal(route.request().method(), 'POST')
      recoveryRequests.push(url.pathname)
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
  } else if (url.pathname.includes('token-usage')) {
    if (tokenUnavailable) { status = 503; body = { detail: 'sub2api 暂不可用' } }
    else body = tokenPayload(Number(url.pathname.match(/\/users\/(\d+)$/)?.[1] || 99))
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(`${baseURL}/admin/dashboard/personal/token-usage?tab=credits`)
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/dashboard/personal/credit-usage')
  assert.equal(await page.locator('.usage-tabs').count(), 0)
  await page.getByRole('heading', { name: '我的用量 / 积分用量', exact: true }).waitFor()
  assert.equal(await page.locator('.credit-usage .el-table__body tbody tr').count(), 16)
  assert.equal(await page.getByRole('tab', { name: '用户排行', exact: true }).count(), 0)
  assert.equal(requests.filter(url => url.pathname.includes('token-usage')).length, 0)
  await ready()
  await page.getByRole('button', { name: '恢复对话', exact: true }).click()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(recoveryRequests.length, 0, 'Cancelling confirmation must not recover a run')
  await page.getByRole('button', { name: '恢复对话', exact: true }).click()
  await page.getByRole('button', { name: '确认恢复', exact: true }).click()
  await page.getByText('处理完成，已结算实际用量并返还剩余预占积分', { exact: true }).waitFor()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert(recoveryRequests[0].includes('/personal/credit-usage/runs/run-3/recover'))
  assert.equal(await page.getByRole('button', { name: '恢复对话', exact: true }).count(), 0)
  await page.screenshot({ path: path.join(output, 'personal-desktop.png'), fullPage: true, animations: 'disabled' })
  await page.locator('.credit-pagination .btn-next').click()
  await page.getByText('Conversation 17', { exact: true }).waitFor()
  assert(requests.some(url => url.pathname.endsWith('/credit-usage/runs') && url.searchParams.get('skip') === '16'))
  await page.getByRole('tab', { name: '收支流水', exact: true }).click()
  await page.getByText('结算解冻返还', { exact: true }).first().waitFor()
  await usageMenu('我的用量').getByRole('menuitem', { name: 'Token 用量（sub2api）', exact: true }).click()
  await page.getByText('Key 10', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/dashboard/personal/token-usage')
  await page.locator('.recent-card .pagination-container .btn-next').click()
  await page.getByText('Key 11', { exact: true }).waitFor()
  await page.getByPlaceholder('输入 API Key 或模型名称').fill('Key 20')
  await page.getByPlaceholder('输入 API Key 或模型名称').press('Enter')
  await page.getByText('Key 20', { exact: true }).waitFor()
  assert.equal(await page.locator('.recent-card .el-table__body tbody tr').count(), 1)
  await page.getByRole('button', { name: '打开账户信息', exact: true }).click()
  const accountPanel = page.locator('.account-panel:visible')
  await accountPanel.getByRole('button', { name: '积分用量', exact: true }).waitFor()
  await accountPanel.getByRole('button', { name: 'Token 用量（sub2api）', exact: true }).waitFor()
  await page.screenshot({ path: path.join(output, 'account-usage-links.png'), animations: 'disabled' })
  await accountPanel.getByRole('button', { name: '积分用量', exact: true }).click()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/dashboard/personal/credit-usage')
  await page.getByRole('button', { name: '打开账户信息', exact: true }).click()
  await accountPanel.getByRole('button', { name: 'Token 用量（sub2api）', exact: true }).click()
  await page.getByText('Key 10', { exact: true }).waitFor()

  runs[2].status = 'running'
  runs[2].settlement_status = 'reserved'
  await page.goto(`${baseURL}/admin/dashboard/summary/token-usage?tab=credits`)
  await page.getByRole('heading', { name: '全局用量 / 积分用量', exact: true }).waitFor()
  recoveryMode = 'active'
  await page.getByRole('button', { name: '恢复对话', exact: true }).click()
  await page.getByRole('button', { name: '确认恢复', exact: true }).click()
  await page.getByText('该对话仍在执行，请先在对话中停止；执行进程失联后可恢复', { exact: true }).first().waitFor()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  recoveryMode = 'pending_reconciliation'
  await page.getByRole('button', { name: '恢复对话', exact: true }).click()
  await page.getByRole('button', { name: '确认恢复', exact: true }).click()
  await page.getByText('对话已结束，用量记录尚不完整，预占积分保留待对账', { exact: true }).waitFor()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert(recoveryRequests.at(-1).includes('/summary/credit-usage/runs/run-3/recover'))
  recoveryMode = 'settled'
  const recoveredRow = page.locator('.credit-usage .el-table__body tbody tr').filter({ hasText: 'Conversation 3' }).first()
  await recoveredRow.getByRole('button', { name: '重试结算', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '重试结算', exact: true }).click()
  await page.getByText('处理完成，已结算实际用量并返还剩余预占积分', { exact: true }).waitFor()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/dashboard/summary/credit-usage')
  await usageMenu('全局用量').getByRole('menuitem', { name: 'Token 用量（sub2api）', exact: true }).click()
  await page.getByRole('heading', { name: '全局用量 / Token 用量', exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/dashboard/summary/token-usage')
  await page.locator('.usage-table').getByText('Example', { exact: true }).click()
  const tokenDialog = page.getByRole('dialog')
  await tokenDialog.getByText('Key 5', { exact: true }).waitFor()
  await tokenDialog.locator('.pagination-container .btn-next').click()
  await tokenDialog.getByText('Key 6', { exact: true }).waitFor()
  await ready()
  await page.screenshot({ path: path.join(output, 'global-token-detail.png'), fullPage: true, animations: 'disabled' })
  await tokenDialog.locator('.el-dialog__headerbtn').click()
  await page.locator('.usage-table').getByText('Second', { exact: true }).click()
  await tokenDialog.getByText('Key 5', { exact: true }).waitFor()
  assert(requests.some(url => url.pathname.endsWith('/summary/token-usage/users/100')))
  assert.equal(requests.filter(url => url.pathname.includes('token-usage') && url.pathname.endsWith('/requests')).length, 0)
  await tokenDialog.locator('.el-dialog__headerbtn').click()
  await usageMenu('全局用量').getByRole('menuitem', { name: '积分用量', exact: true }).click()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  await page.getByRole('tab', { name: '用户排行', exact: true }).click()
  await page.locator('.credit-usage .el-table__body').getByText('张三', { exact: true }).waitFor()
  await page.locator('.credit-usage .el-table__body').getByText('lisi', { exact: true }).waitFor()
  assert.equal(await page.getByRole('columnheader', { name: '用户 ID', exact: true }).count(), 0)
  assert(requests.some(url => url.pathname === '/iam/api/users/' && url.searchParams.get('ids')?.includes('8')))
  await page.getByRole('button', { name: '查看明细', exact: true }).first().click()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert(requests.some(url => url.pathname.endsWith('/summary/credit-usage') && url.searchParams.get('user_id') === '7'))
  await page.locator('.credit-usage .el-table__body').getByText('张三', { exact: true }).first().waitFor()
  assert.equal(await page.locator('.user-select .el-select__selected-item').filter({ hasText: '张三' }).count(), 1)
  await page.getByRole('button', { name: '全部用户', exact: true }).click()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  await ready()
  await page.screenshot({ path: path.join(output, 'global-desktop.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '收起主菜单', exact: true }).click()
  await usageMenu('全局用量').locator('.el-sub-menu__title').hover()
  await page.getByRole('menuitem', { name: 'Token 用量（sub2api）', exact: true }).click()
  await page.getByRole('heading', { name: '全局用量 / Token 用量', exact: true }).waitFor()
  await page.getByRole('button', { name: '展开主菜单', exact: true }).click()
  await usageMenu('全局用量').getByRole('menuitem', { name: '积分用量', exact: true }).click()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  await ready()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'global-mobile.png'), fullPage: true, animations: 'disabled' })
  await page.locator('.credit-pagination').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'global-mobile-table.png'), fullPage: true, animations: 'disabled' })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
  const filterFits = await page.locator('.credit-filters').evaluate(element => element.scrollWidth <= element.clientWidth)
  assert(filterFits, 'Credit filters overflow mobile width')

  tokenUnavailable = true
  await page.goto(`${baseURL}/admin/dashboard/personal/token-usage?tab=tokens`)
  await page.getByText('sub2api 暂不可用', { exact: true }).first().waitFor()
  await page.getByRole('button', { name: '打开主菜单', exact: true }).click()
  await usageMenu('我的用量').getByRole('menuitem', { name: '积分用量', exact: true }).click()
  await page.getByText('Conversation 16', { exact: true }).waitFor()
  assert.equal(await page.locator('.credit-usage .el-alert--error').count(), 0)
  isSuperuser = false
  tokenUnavailable = false
  await page.goto(`${baseURL}/admin/dashboard/summary/credit-usage`)
  await page.getByText('Key 10', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/dashboard/personal/token-usage')
  assert.equal(await usageMenu('全局用量').count(), 0)
  assert.deepEqual(errors, [])
  console.log('Usage dashboard browser checks passed: four pages, sidebar and account links, legacy redirects, pagination, search, user drill-down, mobile, independent failures.')
  console.log(`Screenshots: ${output}`)
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  console.error({ url: page.url(), errors, requests: requests.map(url => url.pathname), body: (await page.locator('body').innerText()).slice(0, 1600) })
  throw error
} finally {
  await context.close()
  await browser.close()
}
