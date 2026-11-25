import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const frame = event => `data: ${JSON.stringify(event)}\n\n`

try {
  for (const path of ['/workspace/chat', '/admin/agents/1/chat', '/workspace/chat?agent=1']) {
    const hasBootstrapCredit = path.includes('?agent=')
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const page = await context.newPage()
    page.setDefaultTimeout(10000)
    const errors = []
    let failCredits = false
    let savedHistory = false
    let creditRequests = 0
    let releaseCredits
    const creditGate = new Promise(resolve => { releaseCredits = resolve })
    const account = { claimed_today: true, available_balance: 100, display_name: '趣点' }
    const model = { id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'platform' }
    const agent = { id: 1, name: '测试助手', icon: 'H', kind: 'expert', runtime_type: 'claude_code',
      default_model_id: 1, models: [model], skills: [], prompt_templates: [], mcp_connections: [] }
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'chat-credit-label-test-only')
      const original = window.fetch
      window.fetch = async (url, options) => {
        const response = await original(url, options)
        if (!response.headers.get('content-type')?.includes('text/event-stream')) return response
        const initial = await response.text()
        const encoder = new TextEncoder()
        return new Response(new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(initial))
            window.finishCreditStream = suffix => {
              controller.enqueue(encoder.encode(suffix))
              controller.close()
            }
            options.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), { once: true })
          },
        }), { headers: response.headers })
      }
    })
    await page.route('**/*', async route => {
      const request = route.request(), pathname = new URL(request.url()).pathname
      if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (pathname === '/iam/api/me') body = { id: 7, username: 'credit-label-test', permissions: [] }
      else if (pathname.endsWith('/bootstrap')) body = {
        assistant_id: 1, assistant: agent, ...(hasBootstrapCredit ? { credit: account } : {}),
      }
      else if (pathname.endsWith('/credits/me')) {
        creditRequests++
        if (failCredits) return route.fulfill({ status: 503, json: { detail: 'temporary failure' } })
        await creditGate
        body = account
      } else if (pathname === '/aihub/api/agents/1') body = agent
      else if (pathname.endsWith('/models')) body = { items: [model], total: 1 }
      else if (pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
      else if (pathname.endsWith('/skills/sync')) body = { status: 'synced' }
      else if (pathname.endsWith('/files')) body = { files: [] }
      else if (savedHistory && pathname.endsWith('/sessions/3/messages') && request.method() === 'GET') body = {
        session: { id: 3, agent_id: 1, source: 'web', model_id: 1 },
        items: [{ id: 7, role: 'assistant', charged_points: 13.2, content: JSON.stringify({
          blocks: [
            { type: 'text', content: '已保存的部分回复' },
            { type: 'error', content: '模型请求超时', error_code: 'model_request_timeout',
              metadata: { error_origin: 'model_connection', error_detail: 'API Error: 504 upstream_timeout; request_id=req-history' } },
          ], usage: { input_tokens: 10, output_tokens: 10 },
        }) }],
      }
      else if (pathname === '/aihub/api/agents/1/messages' && request.method() === 'POST') {
        return route.fulfill({ contentType: 'text/event-stream', body: [
          { type: 'run_start', run_id: 'credit-run', session_id: 3 },
          { type: 'text', content: '测试回复' },
          { type: 'credit_usage', metadata: { charged_points: 13.2, available_balance: 86.8 } },
        ].map(frame).join('') })
      }
      return route.fulfill({ json: body })
    })
    try {
      await page.goto(base + path)
      const send = async () => {
        await page.locator('.inline-composer .cm-content').fill('测试消耗单位')
        await page.getByRole('button', { name: '发送', exact: true }).click()
        await page.getByText('测试回复', { exact: true }).last().waitFor()
      }
      const usage = page.locator('.stream-run-meta')
      await send()
      if (hasBootstrapCredit) {
        await page.waitForFunction(() => /已消耗\s+13\.20\s+趣点/.test(document.querySelector('.stream-run-meta')?.textContent))
      } else {
        assert.ok(creditRequests >= 2, 'Both the layout and chat must load the account on entry')
        assert.doesNotMatch(await usage.innerText(), /已消耗|积分/, 'Do not invent a unit while configuration is loading')
      }
      releaseCredits()
      await page.waitForFunction(() => /已消耗\s+13\.20\s+趣点/.test(document.querySelector('.stream-run-meta')?.textContent))

      // Completing a run refreshes the account. A failed refresh must retain the unit.
      failCredits = true
      const failedRefresh = page.waitForResponse(response => response.url().endsWith('/credits/me') && response.status() === 503)
      await page.evaluate(suffix => window.finishCreditStream(suffix), [
        { type: 'turn_metrics', charged_points: 13.2, usage: { input_tokens: 10, output_tokens: 10 }, duration_ms: 1000 },
        { type: 'done' }, { type: 'stream_end', status: 'succeeded' },
      ].map(frame).join(''))
      await failedRefresh
      await page.waitForFunction(() => /共消耗\s*13\.20\s*趣点/.test(document.querySelector('.turn-metrics')?.textContent))
      await send()
      await page.waitForFunction(() => /已消耗\s+13\.20\s+趣点/.test(document.querySelector('.stream-run-meta')?.textContent))

      // Independent expert pages must also receive account updates from other views.
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('aihub:credit-account-updated', {
        detail: { claimed_today: true, available_balance: 100, display_name: '能量值' },
      })))
      await page.waitForFunction(() => /已消耗\s+13\.20\s+能量值/.test(document.querySelector('.stream-run-meta')?.textContent))

      await page.evaluate(suffix => window.finishCreditStream(suffix), [
        { type: 'error', content: '模型请求超时', error_code: 'model_request_timeout',
          metadata: { error_origin: 'model_connection', error_detail: 'API Error: 504 upstream_timeout; request_id=req-browser' } },
        { type: 'turn_metrics', charged_points: null, usage: { input_tokens: 10, output_tokens: 10 }, duration_ms: 1000 },
        { type: 'stream_end', status: 'timed_out' },
      ].map(frame).join(''))
      await page.getByText('模型请求超时', { exact: true }).waitFor()
      const failure = page.getByRole('alert')
      await failure.getByText('错误详情', { exact: true }).click()
      await failure.getByText('API Error: 504 upstream_timeout; request_id=req-browser', { exact: true }).waitFor()
      assert.match(await failure.innerText(), /错误来源：AIHub 到模型上游的连接/)
      await page.waitForFunction(() => [...document.querySelectorAll('.turn-metrics')].some(el => /共消耗\s*13\.20\s*能量值/.test(el.textContent)))

      failCredits = false
      savedHistory = true
      await page.reload()
      await page.getByText('已保存的部分回复', { exact: true }).waitFor()
      await page.getByText('错误详情', { exact: true }).click()
      await page.getByText('API Error: 504 upstream_timeout; request_id=req-history', { exact: true }).waitFor()
      await page.waitForFunction(() => /共消耗\s*13\.20\s*趣点/.test(document.querySelector('.turn-metrics')?.textContent))
      if (path === '/workspace/chat') await page.screenshot({ path: '/private/tmp/aihub-chat-error-history.png', fullPage: true })
      assert.deepEqual(errors, [])
      console.log(`Passed: ${path}: ${hasBootstrapCredit ? 'shared bootstrap account' : 'delayed configuration'}; configured unit; failed refresh; account update event.`)
    } finally {
      releaseCredits()
      await context.close()
    }
  }
} finally {
  await browser.close()
}
