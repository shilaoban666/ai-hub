import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15179'
const output = path.resolve('output/playwright/chat-artifacts')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
page.setDefaultTimeout(15000)
await page.addInitScript(() => {
  if (window.top === window) localStorage.setItem('access_token', 'artifact-test-only')
})
const errors = [], fileReads = []
let missing = false
const longName = '用于检查完整文件名称悬停提示和窄屏显示的商品库存汇总报表.xlsx'
const files = [
  { path: 'output/库存分析.md', name: '库存分析.md', size: 38, is_previewable: true },
  { path: 'output/库存看板.html', name: '库存看板.html', size: 60, is_previewable: true },
  { path: 'output/chart.png', name: 'chart.png', size: 68, is_previewable: true },
  { path: 'output/report.pdf', name: 'report.pdf', size: 50, is_previewable: true },
  { path: `output/${longName}`, name: longName, size: 0, is_previewable: false },
]
const session = { id: 3, title: '商品库存分析', source: 'web', message_count: 2, model_id: 1 }
const messages = [
  { id: 1, role: 'user', content: '请生成库存分析和看板' },
  { id: 2, role: 'assistant', content: JSON.stringify({ blocks: [
    { type: 'text', content: '库存分析已完成，相关文件如下。' }, { type: 'artifacts', files },
  ] }) },
]
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const url = new URL(route.request().url()), method = route.request().method()
  if (url.hostname === 'assets.fancyqube.net') return route.fulfill({ body: '' })
  if (url.pathname === '/func_process_app/iam_sso_session/') return route.fulfill({ json: { code: 0 } })
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
  else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
  else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
  else if (url.pathname === '/aihub/api/models/usable') body = [{ id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'user', is_enabled: true }]
  else if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', kind: 'personal_default', runtime_type: 'claude_code',
    default_model_id: 1, models: [{ id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'user', is_enabled: true }], skills: [] }
  else if (url.pathname.endsWith('/sessions')) body = { items: [session], total: 1 }
  else if (url.pathname.endsWith('/sessions/3/messages')) body = { session, items: messages, has_more: false }
  else if (url.pathname === '/aihub/api/agents/1/messages' && method === 'POST') {
    const nextFile = { name: 'latest.csv', path: 'output/latest.csv', size: 12, is_previewable: true }
    messages.push({ id: 3, role: 'user', content: route.request().postDataJSON().content },
      { id: 4, role: 'assistant', content: JSON.stringify({ blocks: [{ type: 'text', content: '新增报表已生成。' }, { type: 'artifacts', files: [nextFile] }] }) })
    return route.fulfill({ contentType: 'text/event-stream', body: [
      { type: 'run_start', run_id: 'artifact-run', session_id: 3 },
      { type: 'text', content: '新增报表已生成。' }, { type: 'done' },
      { type: 'artifacts', metadata: { files: [nextFile] } },
      { type: 'turn_metrics', assistant_message_id: 4, duration_ms: 300 },
      { type: 'stream_end', status: 'succeeded' },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
  } else if (url.pathname.endsWith('/files/preview') || url.pathname.endsWith('/files/download')) {
    assert.equal(route.request().headers().authorization, 'Bearer artifact-test-only')
    const requestedPath = url.searchParams.get('path')
    fileReads.push(requestedPath)
    if (missing) return route.fulfill({ status: 404, json: { detail: '文件不存在' } })
    if (url.pathname.endsWith('/preview')) body = {
      name: requestedPath.split('/').at(-1), path: requestedPath, size: 60, line_count: 2,
      content: requestedPath.endsWith('.html') ? '<!doctype html><html><body><h1>库存看板</h1></body></html>' : '# 库存分析\n当前库存正常。',
    }
    else if (requestedPath.endsWith('.png')) return route.fulfill({ contentType: 'application/octet-stream', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7wsAAAAASUVORK5CYII=', 'base64') })
    else return route.fulfill({ contentType: 'application/octet-stream', body: requestedPath.endsWith('.pdf') ? '%PDF-1.4\n%%EOF' : 'sku,count\na,2' })
  }
  await route.fulfill({ json: body })
})
const card = page.locator('.chat-artifacts').first()
const closePreview = async () => {
  await page.locator('.el-dialog:visible .el-dialog__headerbtn').click()
  await page.locator('.el-dialog:visible').waitFor({ state: 'hidden' })
}

try {
  await page.goto(`${base}/admin/chat?session=3`)
  await card.waitFor()
  assert.equal(await card.locator('.artifact-row').count(), 5)
  assert.deepEqual(fileReads, [], 'Rendering lists does not read file contents')
  assert.equal(await card.getByText('查看变更', { exact: true }).count(), 0)
  assert.equal(await card.getByText('撤销', { exact: true }).count(), 0)
  assert.equal(await card.getByRole('button', { name: `预览 ${longName}`, exact: true }).isDisabled(), true)
  assert.equal(await card.locator('.artifact-path').last().getAttribute('title'), `output/${longName}`)
  await card.getByRole('button', { name: '预览 库存分析.md', exact: true }).hover()
  await page.getByRole('tooltip', { name: '预览文件', exact: true }).waitFor()
  await card.getByRole('button', { name: '预览 库存分析.md', exact: true }).click()
  await page.getByRole('dialog', { name: '库存分析.md', exact: true }).getByRole('heading', { name: '库存分析', exact: true }).waitFor()
  await closePreview()

  await card.getByRole('button', { name: '预览 库存看板.html', exact: true }).click()
  const htmlFrame = page.getByRole('dialog', { name: '库存看板.html', exact: true }).locator('iframe')
  await htmlFrame.waitFor()
  assert.equal(await htmlFrame.getAttribute('sandbox'), 'allow-scripts')
  await page.frameLocator('.artifact-frame').getByRole('heading', { name: '库存看板' }).waitFor()
  await closePreview()
  await card.getByRole('button', { name: '预览 chart.png', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.artifact-image')?.naturalWidth > 0)
  await closePreview()
  await card.getByRole('button', { name: '预览 report.pdf', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.artifact-frame')?.src.startsWith('blob:'))
  await closePreview()

  const download = page.waitForEvent('download')
  await card.getByRole('button', { name: `下载 ${longName}`, exact: true }).click()
  assert.equal((await download).suggestedFilename(), longName)
  missing = true
  await card.getByRole('button', { name: '预览 库存分析.md', exact: true }).click()
  await page.getByText('文件不存在', { exact: true }).first().waitFor()
  await page.locator('.el-dialog:visible').waitFor({ state: 'hidden' })
  await card.getByRole('button', { name: '下载 库存分析.md', exact: true }).click()
  await page.waitForTimeout(150)
  assert.equal(await card.locator('.artifact-row').count(), 5)
  missing = false

  const input = page.getByPlaceholder('输入问题或任务')
  await input.fill('再生成一份 CSV')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.locator('.chat-artifacts').nth(1).getByText('output/latest.csv', { exact: true }).waitFor()
  assert.equal(await page.locator('.chat-artifacts').count(), 2, 'Live artifacts belong to their own assistant reply')
  assert.equal(await page.locator('.chat-artifacts').nth(1).locator('.artifact-row').count(), 1)
  await page.reload()
  await page.locator('.chat-artifacts').nth(1).waitFor()
  assert.equal(await page.locator('.chat-artifacts').count(), 2, 'Saved artifacts survive refresh')
  await page.locator('.chat-artifacts').nth(1).scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'desktop.png'), animations: 'disabled' })

  await page.setViewportSize({ width: 390, height: 844 })
  await card.scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'mobile.png'), animations: 'disabled' })
  assert.equal(await card.evaluate(element => element.scrollWidth <= element.clientWidth), true)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  assert.deepEqual(errors, [])
  console.log('PASS: history/live lists, preview tooltips, Markdown/HTML/image/PDF preview, download, missing files, refresh and mobile layout')
} finally {
  await browser.close()
}
