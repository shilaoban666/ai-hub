import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15179'
const output = path.resolve('../output/playwright/chat-permissions')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const frame = events => `data: ${JSON.stringify({ type: 'run_snapshot', revision: 3, events })}\n\n`

try {
  for (const [tool, input, detail, button, decision, remember, terminalCode] of [
    ['Bash', { command: 'printf ok > approved.txt' }, 'printf ok > approved.txt', '本次允许', 'allow', false],
    ['Write', { file_path: 'approved.txt', content: 'ok' }, 'approved.txt', '本次拒绝', 'deny', false],
    ['mcp__knowledge__update', { record_id: 7, enabled: false }, '"enabled": false', '本轮始终允许', 'allow', true],
    ...['expired', 'already_processed', 'run_ended', 'not_found'].map(code => (
      ['Write', { file_path: 'expired.txt' }, 'expired.txt', '本次允许', 'allow', false, code]
    )),
  ]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const page = await context.newPage()
    page.setDefaultTimeout(12000)
    let active = false, rejectSubmission = true, sent
    const decisions = [], errors = []
    let releaseSubmission, submissionReceived
    const firstSubmission = new Promise(resolve => { submissionReceived = resolve })
    const events = [
      { type: 'run_start', run_id: 'permission-run', session_id: 3 },
      { type: 'permission_request', req_id: 'request-1', run_id: 'permission-run', tool_name: tool, tool_input: input },
    ]
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'permission-browser-test')
      const fetchOriginal = window.fetch
      window.fetch = async (url, options) => {
        const response = await fetchOriginal(url, options)
        if (!response.headers.get('content-type')?.includes('text/event-stream')) return response
        const initial = await response.text(), encoder = new TextEncoder()
        return new Response(new ReadableStream({ start(controller) {
          controller.enqueue(encoder.encode(initial))
          window.pushPermissionStream = suffix => controller.enqueue(encoder.encode(suffix))
          window.finishPermissionStream = suffix => {
            controller.enqueue(encoder.encode(suffix))
            controller.close()
          }
          options.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), { once: true })
        } }), { headers: response.headers })
      }
    })
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'test', permissions: [] }
      else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
      else if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: '默认助手', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
      else if (url.pathname.endsWith('/sessions')) body = { total: active ? 1 : 0, items: active ? [{ id: 3, source: 'web', title: '授权测试', active_run_id: 'permission-run', active_run_status: 'running' }] : [] }
      else if (url.pathname.endsWith('/sessions/3/messages')) body = { session: { id: 3, source: 'web', model_id: 1, active_run_id: 'permission-run', active_run_status: 'running' }, items: [{ id: 1, role: 'user', content: '授权测试' }] }
      else if (url.pathname.endsWith('/agents/1/messages') && request.method() === 'POST') {
        sent = request.postDataJSON()
        active = true
        return route.fulfill({ contentType: 'text/event-stream', body: frame(events) })
      } else if (url.pathname.endsWith('/runs/permission-run/events')) {
        return route.fulfill({ contentType: 'text/event-stream', body: frame(events) })
      } else if (url.pathname.endsWith('/permission/decide')) {
        decisions.push(request.postDataJSON())
        if (decisions.length === 1) {
          await new Promise(resolve => { releaseSubmission = resolve; submissionReceived() })
        }
        body = rejectSubmission ? { ok: false, detail: '模拟授权保存失败' }
          : terminalCode ? { ok: false, resolved: true, code: terminalCode, detail: `授权已失效：${terminalCode}` }
          : { ok: true }
      }
      return route.fulfill({ json: body })
    })
    try {
      await page.goto(`${base}/admin/chat`)
      await page.getByRole('button', { name: '选择权限模式' }).click()
      await page.getByRole('menuitem').filter({ hasText: '逐次确认' }).click()
      const composer = page.locator('.workspace-chat .inline-composer .cm-content')
      await composer.fill('授权测试')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '需要授权' })
      await dialog.waitFor()
      assert.equal(sent.permission_mode, 'default')
      assert.equal(await page.getByRole('button', { name: button, exact: true }).count(), 1)
      assert.equal(await page.locator('.permission-bar').count(), 0)
      assert.ok((await dialog.locator('.dialog-detail').innerText()).includes(detail))
      await dialog.getByRole('button', { name: button, exact: true }).evaluate(el => { el.click(); el.click() })
      await firstSubmission
      await page.waitForFunction(() => [...document.querySelectorAll('.dialog-actions button')].every(el => el.disabled))
      assert.equal(decisions.length, 1)
      releaseSubmission()
      await page.getByText('模拟授权保存失败', { exact: true }).waitFor()
      assert.ok(await dialog.isVisible())

      // Reconnect into an in-flight request and verify the same modal returns.
      await page.reload()
      await dialog.waitFor()
      rejectSubmission = false
      await page.waitForTimeout(350) // Let the dialog's opening transition finish for visual QA.
      await page.screenshot({ path: path.join(output, `${tool.replaceAll('_', '-')}.png`) })
      await dialog.getByRole('button', { name: button, exact: true }).click()
      await dialog.waitFor({ state: 'hidden' })
      if (terminalCode) await page.getByText(`授权已失效：${terminalCode}`, { exact: true }).waitFor()
      assert.equal(decisions.at(-1).decision, decision)
      assert.equal(decisions.at(-1).remember, remember)
      assert.equal(decisions.at(-1).run_id, 'permission-run')
      assert.equal(decisions.at(-1).req_id, 'request-1')
      // A later checkpoint can still contain the now-resolved request.
      await page.evaluate(events => window.pushPermissionStream(`data: ${JSON.stringify({
        type: 'run_snapshot', revision: 4, events: [...events, { type: 'text', content: '重放完成' }],
      })}\n\n`), events)
      await page.getByText('重放完成', { exact: true }).waitFor()
      assert.equal(await dialog.isVisible(), false)
      await page.evaluate(() => window.finishPermissionStream('data: {"type":"stream_end","status":"succeeded"}\n\n'))
      assert.deepEqual(errors, [])
    } finally {
      await context.close()
    }
  }
  console.log('Permission browser checks passed: Bash, Write, MCP; double-click guard, allow/deny/remember, retry, reload, stale replay, terminal request cleanup.')
} finally {
  await browser.close()
}
