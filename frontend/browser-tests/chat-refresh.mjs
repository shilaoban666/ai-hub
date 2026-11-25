import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15178'
const output = path.resolve('../output/playwright/chat-refresh')
await mkdir(output, { recursive: true })
const snapshotFrame = (events, revision) => `id: ${revision}\ndata: ${JSON.stringify({ type: 'run_snapshot', revision, events })}\n\n`
const browser = await chromium.launch({ channel: 'msedge', headless: true })

try {
  for (const stop of [false, true]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const page = await context.newPage()
    let posts = 0
    let reconnects = 0
    let cancels = 0
    let status = null
    const errors = []
    const question = '验证刷新后继续运行'
    const firstText = '刷新前已生成的内容。'
    const finalText = firstText + '刷新后继续生成的内容。'
    const session = () => ({ id: 3, agent_id: 1, user_id: 7, title: question, source: 'web', model_id: 1,
      message_count: status === 'succeeded' ? 2 : 1, active_run_id: status === 'running' ? 'refresh-run' : null,
      active_run_status: status === 'running' ? 'running' : null })
    const events = [
      { type: 'run_queued', run_id: 'refresh-run', session_id: 3, user_content: question },
      { type: 'run_start', run_id: 'refresh-run', session_id: 3 },
      { type: 'text', content: firstText },
    ]
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'refresh-test')
      const original = window.fetch
      window.fetch = async (url, options) => {
        const response = await original(url, options)
        if (!response.headers.get('content-type')?.includes('text/event-stream')) return response
        const initial = await response.text()
        const encoder = new TextEncoder()
        return new Response(new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(initial))
            window.dropChatStream = () => controller.close()
            window.finishChatStream = suffix => {
              controller.enqueue(encoder.encode(suffix))
              controller.close()
            }
            options.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), { once: true })
          },
        }), { headers: response.headers })
      }
    })
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'refresh-test', permissions: [] }
      if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, display_name: '算点', available_balance: 100 }
      if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
      if (url.pathname.endsWith('/sessions')) body = { total: status ? 1 : 0, items: status ? [session()] : [] }
      if (url.pathname.endsWith('/sessions/3/messages')) body = {
        session: session(), items: [{ id: 1, role: 'user', content: question },
          ...(status === 'succeeded' ? [{ id: 2, role: 'assistant', content: JSON.stringify([{ type: 'text', content: finalText }]) }] : [])],
      }
      if (url.pathname === '/aihub/api/agents/1/messages') {
        posts++
        status = 'running'
        return route.fulfill({ contentType: 'text/event-stream', body: snapshotFrame(events, 3) })
      }
      if (url.pathname.endsWith('/runs/refresh-run/events')) {
        reconnects++
        const after = Number(url.searchParams.get('after') || 0)
        return route.fulfill({ contentType: 'text/event-stream', body: after < 3 ? snapshotFrame(events, 3) : '' })
      }
      if (url.pathname.endsWith('/runs/refresh-run/cancel')) {
        cancels++
        status = 'cancelled'
        await page.evaluate(suffix => window.finishChatStream(suffix), snapshotFrame([...events, { type: 'cancelled' }, { type: 'stream_end', status: 'cancelled' }], 5))
        body = { cancel_requested: true }
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto(`${base}/workspace/chat`)
    const input = page.getByPlaceholder('输入问题或任务')
    await input.fill(question)
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByText(firstText, { exact: true }).waitFor()
    await page.waitForURL('**/workspace/chat?session=3')
    assert.equal(posts, 1)
    const reconnected = page.waitForResponse(response => response.url().includes('/events?after=3'))
    await page.evaluate(() => window.dropChatStream())
    await reconnected
    assert.equal(await page.getByText(firstText, { exact: true }).count(), 1)
    assert.equal(posts, 1)
    await page.reload()
    await page.getByText(firstText, { exact: true }).waitFor()
    await page.locator('.session-running').waitFor()
    assert.equal(cancels, 0)
    assert.equal(posts, 1)
    assert(reconnects >= 1)
    // Opening the history list without a selected conversation still shows loading.
    await page.goto(`${base}/workspace/chat`)
    await page.locator('.session-running').waitFor()
    await page.locator('.session-item').filter({ hasText: question }).click()
    await page.getByText(firstText, { exact: true }).waitFor()
    assert.equal(await page.getByText(question, { exact: true }).count(), 2) // sidebar + one user message
    await page.screenshot({ path: path.join(output, stop ? 'restored-before-stop.png' : 'restored-running.png') })
    if (stop) {
      await page.getByRole('button', { name: '停止生成', exact: true }).click()
    } else {
      status = 'succeeded'
      const finish = `id: 7\ndata: ${JSON.stringify({ type: 'run_delta', events: [
        { type: 'text', content: '刷新后继续生成的内容。' }, { type: 'done' },
        { type: 'turn_metrics', assistant_message_id: 2, duration_ms: 1500, charged_points: 1 },
        { type: 'stream_end', status: 'succeeded' },
      ] })}\n\n`
      await page.evaluate(suffix => window.finishChatStream(suffix), finish)
      await page.getByText(finalText, { exact: true }).waitFor()
    }
    await page.locator('.session-running').waitFor({ state: 'detached' })
    assert.equal(posts, 1)
    assert.equal(cancels, stop ? 1 : 0)
    assert.deepEqual(errors, [])
    await page.screenshot({ path: path.join(output, stop ? 'stopped.png' : 'completed.png') })
    await context.close()
    console.log(`refresh + history reattachment + ${stop ? 'explicit stop' : 'completion'} passed`)
  }
} finally {
  await browser.close()
}
