import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.CHAT_TEST_URL || 'http://localhost:15173'
const output = path.resolve('output/playwright/message-feedback')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'feedback-test-only'))
const page = await context.newPage()
const errors = [], writes = [], details = []
const votes = new Map()
const processing = new Map()
let failSave = false, isAdmin = true
const session = { id: 3, title: '供应商 SKU 明细查询', source: 'web', message_count: 2, created_at: '2026-09-24T02:00:00Z' }
const messages = [
  { id: 1, role: 'user', content: '查询供应商 SKU 明细' },
  { id: 2, role: 'assistant', content: JSON.stringify({ blocks: [{ type: 'text', content: '这是供应商 **SKU 明细**，包含规格与重量。' }] }) },
]
const record = (messageId, value) => ({ id: messageId, message_id: messageId, session_id: 3,
  user_id: 7, display_name: '张三', username: 'zhangsan', session_title: session.title,
  created_at: '2026-09-24T03:00:00Z', updated_at: '2026-09-24T03:00:00Z',
  processing_status: value?.rating === 'dislike' ? 'pending' : null,
  ...value, ...(processing.get(messageId) || {}) })
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const url = new URL(route.request().url()), method = route.request().method()
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }, status = 200
  if (url.pathname === '/iam/api/me') body = { id: 7, username: 'zhangsan', first_name: '张三', is_superuser: isAdmin, permissions: [] }
  else if (url.pathname === '/iam/api/users/') body = { items: [{ id: 8, username: 'lisi', first_name: '李四', is_active: true }], total: 1 }
  else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
  else if (url.pathname.endsWith('/credits/me')) body = { available_balance: 100, claimed_today: true }
  else if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
  else if (url.pathname.endsWith('/sessions')) body = { items: [session], total: 1 }
  else if (url.pathname.endsWith('/sessions/3/messages')) body = { session, items: messages.map(item => ({ ...item, feedback: votes.get(item.id) || null })), has_more: false }
  else if (url.pathname === '/aihub/api/agents/1/messages') {
    messages.push({ id: 3, role: 'user', content: route.request().postDataJSON().content }, { id: 4, role: 'assistant', content: '新增回复可以立即反馈。' })
    return route.fulfill({ contentType: 'text/event-stream', body: [
      { type: 'run_start', run_id: 'feedback-run', session_id: 3 },
      { type: 'text', content: '新增回复可以立即反馈。' }, { type: 'done' },
      { type: 'turn_metrics', assistant_message_id: 4, duration_ms: 100, usage: {} },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
  } else if (url.pathname.startsWith('/aihub/api/feedback/messages/')) {
    const id = Number(url.pathname.split('/').at(-1))
    writes.push({ id, method })
    if (failSave) { status = 503; body = { detail: '反馈暂时不可用' } }
    else if (method === 'DELETE') { votes.delete(id); processing.delete(id); body = {} }
    else {
      const data = route.request().postDataJSON()
      body = { rating: data.rating, reasons: data.reasons || [], comment: data.comment || '' }
      votes.set(id, body)
      if (data.rating === 'like') processing.delete(id)
    }
  } else if (url.pathname === '/aihub/api/feedback') {
    let items = [...votes].map(([id, value]) => record(id, value))
    if (url.searchParams.get('rating')) items = items.filter(item => item.rating === url.searchParams.get('rating'))
    if (url.searchParams.get('processing_status')) items = items.filter(item => item.processing_status === url.searchParams.get('processing_status'))
    if (url.searchParams.get('creator')) items = items.filter(item => `${item.display_name}${item.username}`.includes(url.searchParams.get('creator')))
    if (url.searchParams.get('assignee')) items = items.filter(item => `${item.assignee_name}${item.assignee_username}`.includes(url.searchParams.get('assignee')))
    if (url.searchParams.get('search')) items = items.filter(item => `${item.session_title}${item.reasons.join('、')}${item.comment}`.includes(url.searchParams.get('search')))
    body = { total: items.length, items }
  } else if (/\/feedback\/\d+\/processing$/.test(url.pathname)) {
    assert.equal(method, 'PATCH')
    const id = Number(url.pathname.split('/').at(-2))
    processing.set(id, route.request().postDataJSON())
    body = record(id, votes.get(id))
  } else if (/\/feedback\/\d+$/.test(url.pathname)) {
    const id = Number(url.pathname.split('/').at(-1)), before = url.searchParams.get('before_id')
    details.push(url)
    const scopedMessages = url.searchParams.get('scope') === 'conversation' ? messages : messages.filter(item => item.id <= id)
    body = { feedback: record(id, votes.get(id)), session_deleted: false, can_process: isAdmin, has_more: !before,
      session: { title: session.title, agent_name: 'AI 助手', agent_icon: 'H' },
      items: before ? scopedMessages.filter(item => item.id < Number(before)) : scopedMessages.filter(item => item.id >= id) }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(`${baseURL}/admin/chat?session=3`)
  const like = page.getByRole('button', { name: '点赞', exact: true }).first()
  const dislike = page.getByRole('button', { name: '点踩', exact: true }).first()
  await like.hover()
  await page.getByRole('tooltip', { name: '点赞', exact: true }).waitFor()
  await dislike.hover()
  await page.getByRole('tooltip', { name: '点踩', exact: true }).waitFor()
  await like.click()
  await page.waitForFunction(() => document.querySelector('[aria-label="点赞"]')?.getAttribute('aria-pressed') === 'true')
  assert.equal(votes.get(2).rating, 'like')
  assert.equal(await dislike.getAttribute('aria-pressed'), 'false')
  await like.hover()
  await page.getByRole('tooltip', { name: '撤回点赞', exact: true }).waitFor()
  await page.mouse.move(0, 0)
  await page.waitForFunction(() => getComputedStyle(document.querySelector('[aria-label="点赞"]').closest('.msg-actions')).opacity === '1')
  const selectedStyle = await like.evaluate(element => ({
    fill: getComputedStyle(element.querySelector('svg')).fill,
    opacity: getComputedStyle(element.closest('.msg-actions')).opacity,
  }))
  assert.equal(selectedStyle.fill, 'rgb(80, 80, 80)', 'Selected thumb is solid dark gray')
  assert.equal(selectedStyle.opacity, '1', 'Selected thumb keeps its color without hover')
  await page.reload()
  await like.waitFor()
  assert.equal(await like.getAttribute('aria-pressed'), 'true', 'Saved vote must survive history reload')
  await dislike.click()
  const submitFeedback = page.getByRole('button', { name: '提交反馈', exact: true })
  assert.equal(await page.getByRole('button', { name: '直接看上下文', exact: true }).count(), 0)
  assert.equal(await page.locator('.reason-options button').count(), 7)
  assert.equal(await page.locator('.reason-options button[aria-pressed="true"]').count(), 0)
  assert.equal(await submitFeedback.isEnabled(), true, 'Empty feedback allows immediate submission')
  const popoverBounds = await page.locator('.el-popover:visible').boundingBox()
  const dislikeBounds = await dislike.boundingBox()
  const dislikeCenter = dislikeBounds.x + dislikeBounds.width / 2
  assert(popoverBounds.x <= dislikeCenter && popoverBounds.x + popoverBounds.width >= dislikeCenter,
    'Feedback popover remains aligned with the dislike button')
  assert(Math.min(Math.abs(popoverBounds.y + popoverBounds.height - dislikeBounds.y),
    Math.abs(dislikeBounds.y + dislikeBounds.height - popoverBounds.y)) < 24,
    'Feedback popover stays next to its trigger')
  const codeReason = page.getByRole('button', { name: '代码有错误', exact: true })
  await codeReason.click()
  await codeReason.click()
  assert.equal(await submitFeedback.isEnabled(), true, 'Clearing all reasons still allows submission')
  await page.getByRole('button', { name: '关闭反馈', exact: true }).click()
  await dislike.click()
  assert.equal(await page.locator('.reason-options button[aria-pressed="true"]').count(), 0, 'Reopening starts without a reason')
  await submitFeedback.click()
  await page.waitForFunction(() => document.querySelector('[aria-label="点踩"]')?.getAttribute('aria-pressed') === 'true')
  assert.deepEqual(votes.get(2), { rating: 'dislike', reasons: [], comment: '' })
  await page.reload()
  await dislike.waitFor()
  assert.equal(await dislike.getAttribute('aria-pressed'), 'true', 'Empty feedback survives history reload')
  await page.goto(`${baseURL}/admin/dashboard/summary/feedback`)
  const emptyRow = page.locator('.user-feedback .el-table__body tbody tr').first()
  await emptyRow.waitFor()
  for (const index of [4, 6, 7]) assert.equal((await emptyRow.locator('td').nth(index).innerText()).trim(), '无')
  await emptyRow.getByRole('button', { name: '查看反馈', exact: true }).click()
  await page.getByRole('heading', { name: '反馈详情', exact: true }).waitFor()
  assert.match(page.url(), /\/admin\/feedback\/\d+$/)
  for (const note of await page.locator('.summary-notes dd').all()) assert.equal((await note.innerText()).trim(), '无')
  await page.goto(`${baseURL}/admin/chat?session=3`)
  await dislike.waitFor()
  await dislike.hover()
  await page.getByRole('tooltip', { name: '撤回点踩', exact: true }).waitFor()
  await dislike.click()
  await page.waitForFunction(() => document.querySelector('[aria-label="点踩"]')?.getAttribute('aria-pressed') === 'false')
  await dislike.click()
  await page.getByRole('button', { name: '代码有错误', exact: true }).click()
  await page.getByRole('textbox', { name: '反馈补充说明' }).fill('SKU 的重量单位不对')
  await page.screenshot({ path: path.join(output, 'dislike-form.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '提交反馈', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('[aria-label="点踩"]')?.getAttribute('aria-pressed') === 'true')
  assert.equal(votes.size, 1)
  assert.deepEqual(votes.get(2).reasons, ['代码有错误'])
  assert.equal(votes.get(2).comment, 'SKU 的重量单位不对')
  assert.equal(await like.getAttribute('aria-pressed'), 'false', 'Like and dislike are mutually exclusive')
  assert.equal(await dislike.locator('svg').evaluate(element => getComputedStyle(element).fill), 'rgb(80, 80, 80)')
  failSave = true
  await like.click()
  await page.getByText('反馈暂时不可用', { exact: true }).first().waitFor()
  assert.equal(await dislike.getAttribute('aria-pressed'), 'true', 'Failure must retain existing vote')
  failSave = false
  await dislike.click()
  await page.waitForFunction(() => document.querySelector('[aria-label="点踩"]')?.getAttribute('aria-pressed') === 'false')
  assert.equal(votes.size, 0, 'Second click retracts the vote')
  await dislike.click()
  assert.equal(await submitFeedback.isEnabled(), true)
  await page.getByRole('button', { name: '回答不专业', exact: true }).click()
  await page.getByRole('button', { name: '提交反馈', exact: true }).click()
  await page.locator('.cm-content[contenteditable="true"]').fill('继续查询')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.getByText('新增回复可以立即反馈。', { exact: true }).waitFor()
  await page.getByRole('button', { name: '点赞', exact: true }).last().click()
  await page.waitForFunction(() => [...document.querySelectorAll('[aria-label="点赞"]')].at(-1)?.getAttribute('aria-pressed') === 'true')
  assert.equal(writes.at(-1).id, 4, 'Fresh streamed reply uses persisted message ID')

  await page.goto(`${baseURL}/admin/dashboard/summary/feedback`)
  await page.getByRole('heading', { name: '企业看板 / 用户反馈', exact: true }).waitFor()
  await page.getByRole('menuitem', { name: '用户反馈', exact: true }).waitFor()
  await page.getByText('无需处理', { exact: true }).waitFor()
  const table = page.locator('.user-feedback .el-table')
  const filters = page.locator('.feedback-filters')
  const filterWidths = await filters.locator(':scope > .el-select, :scope > .el-input').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().width))
  assert.equal(filterWidths.length, 5)
  assert(filterWidths.every(width => Math.abs(width - filterWidths[0]) < 1), 'All five search controls have equal widths')
  const ratingFilter = filters.locator('.el-select').first()
  const statusFilter = filters.locator('.el-select').nth(1)
  await ratingFilter.getByText('反馈类型', { exact: true }).waitFor()
  await statusFilter.getByText('处理状态', { exact: true }).waitFor()
  await ratingFilter.click()
  await page.getByRole('option', { name: '点赞', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.user-feedback .el-table__body tbody tr').length === 1)
  await ratingFilter.hover()
  await ratingFilter.locator('.el-select__clear').click()
  await page.waitForFunction(() => document.querySelectorAll('.user-feedback .el-table__body tbody tr').length === 2)
  await statusFilter.click()
  await page.getByRole('option', { name: '待处理', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.user-feedback .el-table__body tbody tr').length === 1)
  await statusFilter.hover()
  await statusFilter.locator('.el-select__clear').click()
  await page.waitForFunction(() => document.querySelectorAll('.user-feedback .el-table__body tbody tr').length === 2)
  const widths = await table.locator('thead th').evaluateAll(cells => cells.slice(0, 5).map(cell => cell.getBoundingClientRect().width))
  assert(widths.every(width => Math.abs(width - widths[0]) < 1), 'First five columns have equal widths')
  await table.getByText('反馈类型', { exact: true }).waitFor()
  assert.equal(await table.getByText('zhangsan', { exact: true }).count(), 0, 'Creator account is not shown below their name')
  assert.equal(await page.getByRole('button', { name: '处理反馈', exact: true }).count(), 1, 'Only dislikes are actionable')
  await page.getByRole('button', { name: '处理反馈', exact: true }).click()
  const processingDialog = page.getByRole('dialog', { name: '处理反馈', exact: true })
  await processingDialog.locator('.el-select').filter({ has: page.getByRole('combobox', { name: '选择处理状态', exact: true }) }).click()
  await page.getByRole('option', { name: '处理中', exact: true }).click()
  await processingDialog.getByRole('combobox', { name: '指定处理人' }).fill('李四')
  await page.getByRole('option', { name: /李四/ }).click()
  await processingDialog.getByRole('button', { name: '保存', exact: true }).click()
  await page.locator('.user-feedback .el-table').getByText('处理中', { exact: true }).waitFor()
  await page.locator('.user-feedback .el-table').getByText('李四', { exact: true }).waitFor()
  assert.equal(processing.get(2).assignee_user_id, 8)
  assert.match(processing.get(2).detail_url, /\/admin\/feedback\/2$/)
  await page.getByRole('button', { name: '处理反馈', exact: true }).click()
  await processingDialog.locator('.el-select').filter({ has: page.getByRole('combobox', { name: '选择处理状态', exact: true }) }).click()
  await page.getByRole('option', { name: '已处理', exact: true }).click()
  await processingDialog.getByRole('button', { name: '保存', exact: true }).click()
  await page.locator('.user-feedback .el-table').getByText('已处理', { exact: true }).waitFor()
  await page.getByRole('textbox', { name: '检索反馈人' }).fill('张三')
  await page.getByRole('textbox', { name: '检索处理人' }).fill('李四')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.user-feedback .el-table__body tbody tr').length === 1)
  await page.locator('.feedback-filters .el-select').first().click()
  await page.getByRole('option', { name: '点踩', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.user-feedback .el-table__body tbody tr').length === 1)
  await table.getByRole('button', { name: session.title, exact: true }).first().click()
  const conversation = page.getByRole('dialog', { name: '完整会话', exact: true })
  await conversation.getByText('新增回复可以立即反馈。', { exact: true }).waitFor()
  await conversation.getByText('查询供应商 SKU 明细', { exact: true }).waitFor()
  assert.equal(page.url(), `${baseURL}/admin/dashboard/summary/feedback`, 'Opening a conversation stays on the feedback page')
  assert.equal(await conversation.evaluate(element => element.classList.contains('el-drawer')), true, 'Full conversation opens in a drawer')
  assert.equal(await conversation.getByText('被反馈回复', { exact: true }).count(), 0, 'Full conversation has no feedback annotation')
  assert.equal(await conversation.getByRole('button', { name: '处理反馈', exact: true }).count(), 0)
  assert.equal(await conversation.getByRole('button', { name: '加载更早消息', exact: true }).count(), 0, 'Full conversation loads all pages automatically')
  assert(details.some(url => url.searchParams.get('scope') === 'conversation' && url.searchParams.get('before_id') === '2'))
  await page.screenshot({ path: path.join(output, 'feedback-full-conversation.png'), fullPage: true, animations: 'disabled' })
  await page.keyboard.press('Escape')
  await conversation.waitFor({ state: 'hidden' })
  await table.getByRole('button', { name: '查看反馈', exact: true }).first().click()
  await page.getByText('被反馈回复', { exact: true }).waitFor()
  assert.equal(page.url(), `${baseURL}/admin/feedback/2`, 'Feedback detail has a stable link')
  assert.equal(await page.getByText('新增回复可以立即反馈。', { exact: true }).count(), 0, 'Context excludes later messages')
  assert.equal(await page.getByRole('button', { name: '点赞', exact: true }).count(), 0, 'Detail must be read-only')
  await page.getByRole('button', { name: '加载更早消息', exact: true }).click()
  await page.getByText('查询供应商 SKU 明细', { exact: true }).waitFor()
  assert(details.some(url => url.searchParams.get('scope') === 'context' && url.searchParams.get('before_id') === '2'))
  assert.equal(await page.getByText('新增回复可以立即反馈。', { exact: true }).count(), 0, 'Loading context history does not include later messages')
  await page.screenshot({ path: path.join(output, 'feedback-detail.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'feedback-detail-mobile.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: '返回', exact: true }).click()
  await page.getByRole('heading', { name: '企业看板 / 用户反馈', exact: true }).waitFor()
  await page.getByRole('textbox', { name: '搜索用户反馈' }).fill('不存在的标题')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByText('暂无用户反馈', { exact: true }).waitFor()
  await page.getByRole('textbox', { name: '搜索用户反馈' }).fill('张三')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByText('暂无用户反馈', { exact: true }).waitFor()
  await page.getByRole('textbox', { name: '搜索用户反馈' }).fill('不专业')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '查看反馈', exact: true }).first().waitFor()
  await page.waitForFunction(() => ![...document.querySelectorAll('.user-feedback .el-loading-mask')].some(element => getComputedStyle(element).display !== 'none'))
  await page.locator('.feedback-filters .el-select').nth(1).click()
  await page.getByRole('option', { name: '已处理', exact: true }).click()
  await page.waitForFunction(() => ![...document.querySelectorAll('.user-feedback .el-loading-mask')].some(element => getComputedStyle(element).display !== 'none'))
  await page.screenshot({ path: path.join(output, 'feedback-list.png'), fullPage: true, animations: 'disabled' })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${baseURL}/admin/chat?session=3`)
  await page.getByRole('button', { name: '点踩', exact: true }).last().click()
  const form = page.getByRole('region', { name: '不满意原因' })
  await form.waitFor()
  const bounds = await form.boundingBox()
  assert(bounds.x >= 0 && bounds.x + bounds.width <= 390, 'Feedback form fits mobile viewport')
  await page.screenshot({ path: path.join(output, 'feedback-mobile.png'), fullPage: true, animations: 'disabled' })
  isAdmin = false
  await page.goto(`${baseURL}/admin/chat?session=3`)
  await page.getByRole('button', { name: '点赞', exact: true }).first().waitFor()
  assert.equal(await page.getByRole('menuitem', { name: '用户反馈', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log('Feedback browser checks passed: save, switch, retract, reload, failure, streamed reply ID, enterprise inbox, read-only context, older messages, search, mobile.')
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  console.error({ url: page.url(), errors })
  throw error
} finally {
  await context.close()
  await browser.close()
}
