import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.CHAT_TEST_URL || 'http://localhost:15173'
const output = path.resolve('output/playwright/feedback-detail-page')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : { channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' }),
  headless: true,
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'feedback-detail-test-only'))
const page = await context.newPage()
const errors = [], processingWrites = []
let isAdmin = true
let feedback = {
  id: 2, message_id: 2, session_id: 3, user_id: 7,
  display_name: '张三', username: 'zhangsan', session_title: '供应商 SKU 明细查询',
  rating: 'dislike', reasons: ['代码有错误'], comment: 'SKU 的重量单位不对',
  processing_status: 'pending', assignee_user_id: null, assignee_name: null, assignee_username: null,
  created_at: '2026-09-24T03:00:00Z', updated_at: '2026-09-24T03:00:00Z',
}
const detail = () => ({
  feedback, session_deleted: false, can_process: isAdmin, can_assign: isAdmin, has_more: false,
  session: { title: feedback.session_title, agent_name: 'AI 助手', agent_icon: 'H' },
  items: [
    { id: 1, role: 'user', content: '查询供应商 SKU 明细' },
    { id: 2, role: 'assistant', content: JSON.stringify({ blocks: [{ type: 'text', content: '这是供应商 SKU 明细。' }] }) },
  ],
})

page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const url = new URL(route.request().url()), method = route.request().method()
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }, status = 200
  if (url.pathname === '/iam/api/me') body = { id: isAdmin ? 7 : 8, username: isAdmin ? 'zhangsan' : 'lisi', first_name: isAdmin ? '张三' : '李四', is_superuser: isAdmin, permissions: [] }
  else if (url.pathname === '/iam/api/users/') body = { items: [{ id: 8, username: 'lisi', first_name: '李四', is_active: true }], total: 1 }
  else if (url.pathname.endsWith('/credits/me')) body = { available_balance: 100, claimed_today: true }
  else if (url.pathname === '/aihub/api/feedback/2' && method === 'GET') body = detail()
  else if (url.pathname === '/aihub/api/feedback/2/processing' && method === 'PATCH') {
    const data = route.request().postDataJSON()
    processingWrites.push(data)
    feedback = { ...feedback, ...data }
    body = { ...feedback, notification_sent: data.action === 'assignment', resolution_notification_sent: data.processing_status === 'resolved' }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(`${baseURL}/admin/feedback/2`)
  await page.getByRole('heading', { name: '反馈详情', exact: true }).waitFor()
  assert.equal(page.url(), `${baseURL}/admin/feedback/2`)
  await page.getByText('SKU 的重量单位不对', { exact: true }).waitFor()
  await page.getByText('被反馈回复', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '点赞', exact: true }).count(), 0, 'Detail is read-only')

  await page.getByRole('button', { name: '分配处理人', exact: true }).click()
  const assignment = page.getByRole('dialog', { name: '分配处理人', exact: true })
  await assignment.getByRole('combobox').fill('李四')
  await page.getByRole('option', { name: /李四/ }).click()
  await assignment.getByRole('button', { name: '保存', exact: true }).click()
  await assignment.waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '处理反馈', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '处理反馈', exact: true })
  await dialog.locator('.el-select').click()
  assert.deepEqual(await page.getByRole('option').allTextContents(), ['待处理', '已处理'])
  await page.getByRole('option', { name: '已处理', exact: true }).click()
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByText('处理信息已保存，已通知反馈人', { exact: true }).waitFor()
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(processingWrites.length, 2)
  assert.equal(processingWrites[1].processing_status, 'resolved')
  assert.equal(processingWrites[0].assignee_user_id, 8)
  assert.equal(processingWrites[0].detail_url, `${baseURL}/admin/feedback/2`)
  await page.getByText('李四', { exact: true }).first().waitFor()

  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'Detail fits mobile width')
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true, animations: 'disabled' })

  isAdmin = false
  await page.reload()
  await page.getByRole('heading', { name: '反馈详情', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '处理反馈', exact: true }).count(), 0, 'Assignee has read-only access')
  assert.deepEqual(errors, [])
  console.log('Feedback detail page browser checks passed.')
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  console.error({ url: page.url(), errors })
  throw error
} finally {
  await context.close()
  await browser.close()
}
